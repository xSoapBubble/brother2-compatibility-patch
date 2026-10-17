#include "rea_audio_api.h"
#include <math.h>

/* Only calls on already valid IDirectSoundBuffer objects supplied by the game.
 * Never discovers devices, opens mixers, or changes Windows/session volume.
 * COM slots are IUnknown::AddRef=1, Release=2 and DSBuffer::SetVolume=15. */
typedef ULONG (WINAPI *REA_ComRef)(void *self);
typedef HRESULT (WINAPI *REA_DsSetVolume)(void *self, LONG attenuation);

typedef struct REA_SoundEntry {
    struct REA_SoundEntry *next;
    void *owner;
    void *buffer;
    LONG authored_db;
} REA_SoundEntry;

/* A corrupt or missed object destructor cannot create an unbounded list.
 * At capacity/OOM, a new sound still receives its current requested gain, but
 * cannot be revisited on a later slider change until it is tracked again. */
#define REA_MAX_TRACKED_SOUNDS 4096u
static SRWLOCK rea_sound_lock = SRWLOCK_INIT;
static REA_SoundEntry *rea_sounds;
static ULONG rea_sound_count;
static ULONG rea_track_calls;
static ULONG rea_remove_calls;
static ULONG rea_apply_calls;
static ULONG rea_set_calls;
static ULONG rea_set_failures;
static ULONG rea_track_failures;
static HRESULT rea_last_volume_error;

/* Root implements the music backend. Called while holding rea_sound_lock, so
 * concurrent Apply calls cannot apply older music snapshots after newer ones.
 * Lock order: engine -> settings snapshot, engine -> music. Settings setters
 * release the settings lock before calling Apply. Music code must never call
 * back into this engine while holding its own music lock. */
extern void REA_AUDIO_CALL REA_ApplyMusicGains(const float gains[REA_AUDIO_VOLUME_COUNT]);

static float rea_safe_gain(float value)
{
    union { float value; unsigned bits; } repr;
    repr.value = value;
    if ((repr.bits & 0x7f800000u) == 0x7f800000u) return 0.5f;
    if (value < 0.0f) return 0.0f;
    if (value > 1.0f) return 1.0f;
    return value;
}

static LONG rea_effect_volume(LONG authored_db, const float gains[REA_AUDIO_VOLUME_COUNT])
{
    double gain = (double)rea_safe_gain(gains[REA_AUDIO_SOUND]) *
                  (double)rea_safe_gain(gains[REA_AUDIO_WAVE]);
    double volume;
    if (gain <= 0.0) return -10000;
    volume = (double)authored_db + 2000.0 * log10(gain);
    if (volume <= -10000.0) return -10000;
    if (volume >= 0.0) return 0;
    /* Nearest hundredth dB; avoid a cast of NaN/overflow and preserve exact
     * authored integral values when the user-selected gains are both 1. */
    return (LONG)(volume - 0.5);
}

static void rea_buffer_add_ref(void *buffer)
{
    void **vtable = *(void ***)buffer;
    ((REA_ComRef)vtable[1])(buffer);
}

static void rea_buffer_release(void *buffer)
{
    void **vtable = *(void ***)buffer;
    ((REA_ComRef)vtable[2])(buffer);
}

/* Caller holds engine lock, as with every statistic/map mutation. */
static void rea_set_buffer_volume(void *buffer, LONG authored_db,
                                  const float gains[REA_AUDIO_VOLUME_COUNT])
{
    void **vtable = *(void ***)buffer;
    HRESULT result;
    ++rea_set_calls;
    if (vtable[15] == NULL) result = E_NOINTERFACE;
    else result = ((REA_DsSetVolume)vtable[15])(buffer,
                                                   rea_effect_volume(authored_db, gains));
    if (FAILED(result)) {
        ++rea_set_failures;
        rea_last_volume_error = result;
    }
}

static REA_SoundEntry **rea_find_sound(void *owner)
{
    REA_SoundEntry **link = &rea_sounds;
    while (*link != NULL && (*link)->owner != owner) link = &(*link)->next;
    return link;
}

static void rea_remove_sound_locked(void *owner)
{
    REA_SoundEntry **link = rea_find_sound(owner);
    REA_SoundEntry *entry = *link;
    if (entry == NULL) return;
    *link = entry->next;
    --rea_sound_count;
    rea_buffer_release(entry->buffer);
    HeapFree(GetProcessHeap(), 0, entry);
}

REA_AUDIO_EXPORT void REA_AUDIO_CALL REA_RemoveSound(void *owner)
{
    if (owner == NULL) return;
    AcquireSRWLockExclusive(&rea_sound_lock);
    ++rea_remove_calls;
    rea_remove_sound_locked(owner);
    ReleaseSRWLockExclusive(&rea_sound_lock);
}

REA_AUDIO_EXPORT void REA_AUDIO_CALL REA_TrackSound(void *owner, void *ds_buffer,
                                                 LONG authored_db)
{
    REA_SoundEntry **link;
    REA_SoundEntry *entry;
    float gains[REA_AUDIO_VOLUME_COUNT];
    if (owner == NULL) return;
    AcquireSRWLockExclusive(&rea_sound_lock);
    ++rea_track_calls;
    if (ds_buffer == NULL) {
        rea_remove_sound_locked(owner);
        ReleaseSRWLockExclusive(&rea_sound_lock);
        return;
    }
    /* Read *after* acquiring engine lock. A snapshot captured before waiting
     * could restore obsolete levels after another thread's SetVolume/Apply. */
    REA_ReadGains(gains);
    link = rea_find_sound(owner);
    entry = *link;
    if (entry == NULL) {
        if (rea_sound_count < REA_MAX_TRACKED_SOUNDS)
            entry = (REA_SoundEntry *)HeapAlloc(GetProcessHeap(), 0, sizeof(*entry));
        if (entry != NULL) {
            rea_buffer_add_ref(ds_buffer);
            entry->owner = owner;
            entry->buffer = ds_buffer;
            entry->next = NULL;
            *link = entry;
            ++rea_sound_count;
        } else {
            ++rea_track_failures;
        }
    } else if (entry->buffer != ds_buffer) {
        void *old_buffer = entry->buffer;
        /* Retain replacement before releasing old: aliasing objects may share
         * a lifetime even when their COM interface addresses differ. */
        rea_buffer_add_ref(ds_buffer);
        entry->buffer = ds_buffer;
        rea_buffer_release(old_buffer);
    }
    if (entry != NULL) {
        /* This is the game's original attenuation, never the already scaled
         * GetVolume result. Repeated configuration changes cannot compound it. */
        entry->authored_db = authored_db;
    }
    rea_set_buffer_volume(ds_buffer, authored_db, gains);
    ReleaseSRWLockExclusive(&rea_sound_lock);
}

void REA_AUDIO_CALL REA_ApplyGains(void)
{
    REA_SoundEntry *entry;
    float gains[REA_AUDIO_VOLUME_COUNT];
    AcquireSRWLockExclusive(&rea_sound_lock);
    ++rea_apply_calls;
    REA_ReadGains(gains);
    for (entry = rea_sounds; entry != NULL; entry = entry->next)
        rea_set_buffer_volume(entry->buffer, entry->authored_db, gains);
    REA_ApplyMusicGains(gains);
    ReleaseSRWLockExclusive(&rea_sound_lock);
}

/* Read-only diagnostics with no caller-owned memory. Indices:
 * 0 live sounds, 1 Track calls, 2 Remove calls, 3 Apply calls,
 * 4 native SetVolume calls, 5 failed SetVolume calls,
 * 6 map capacity/allocation failures, 7 most recent failed HRESULT,
 * 8 configured map capacity. Cumulative counters intentionally wrap as ULONG.
 * An HRESULT failure is recorded and not raised into the game. */
REA_AUDIO_EXPORT ULONG REA_AUDIO_CALL REA_GetSoundStatus(unsigned index)
{
    ULONG value = 0;
    AcquireSRWLockShared(&rea_sound_lock);
    switch (index) {
    case 0: value = rea_sound_count; break;
    case 1: value = rea_track_calls; break;
    case 2: value = rea_remove_calls; break;
    case 3: value = rea_apply_calls; break;
    case 4: value = rea_set_calls; break;
    case 5: value = rea_set_failures; break;
    case 6: value = rea_track_failures; break;
    case 7: value = (ULONG)rea_last_volume_error; break;
    case 8: value = REA_MAX_TRACKED_SOUNDS; break;
    default: break;
    }
    ReleaseSRWLockShared(&rea_sound_lock);
    return value;
}
