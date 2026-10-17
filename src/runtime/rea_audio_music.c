#define COBJMACROS
#define INITGUID
#include "rea_audio_api.h"
#include <dmusici.h>
#include <math.h>

static SRWLOCK music_lock = SRWLOCK_INIT;
static IDirectMusicPerformance *music_performance;
static volatile LONG music_last_result;
static LONG gain_db(float music) {
    double gain = music;
    if (!(gain > 0.0)) return -10000;
    double db = 2000.0 * log10(gain);
    if (db < -10000.0) return -10000;
    if (db > 0.0) return 0;
    return (LONG)db;
}
/* Engine owns serialization across category updates. Lock order is
 * engine->music; registration never calls back into the engine. */
void REA_CALL REA_ApplyMusicGains(const float gains[3]) {
    AcquireSRWLockExclusive(&music_lock);
    if (music_performance) {
        /* Registration can race an older engine snapshot. Read the newest
         * settings under the music lock before applying to the current port. */
        float latest[3]; REA_ReadGains(latest);
        LONG db = gain_db(latest[REA_AUDIO_MUSIC]);
        music_last_result = IDirectMusicPerformance_SetGlobalParam(
            music_performance, &GUID_PerfMasterVolume, &db, sizeof(db));
    }
    ReleaseSRWLockExclusive(&music_lock);
    (void)gains;
}
REA_API void REA_CALL REA_RegisterMusic(void *raw) {
    IDirectMusicPerformance *p = raw;
    AcquireSRWLockExclusive(&music_lock);
    if (p != music_performance) {
        if (p) IDirectMusicPerformance_AddRef(p);
        if (music_performance) IDirectMusicPerformance_Release(music_performance);
        music_performance = p;
    }
    if (p) {
        float gains[3]; REA_ReadGains(gains);
        LONG db = gain_db(gains[REA_AUDIO_MUSIC]);
        music_last_result = IDirectMusicPerformance_SetGlobalParam(
            p, &GUID_PerfMasterVolume, &db, sizeof(db));
    }
    ReleaseSRWLockExclusive(&music_lock);
}
REA_API void REA_CALL REA_UnregisterMusic(void *raw) {
    AcquireSRWLockExclusive(&music_lock);
    if (music_performance == raw) {
        IDirectMusicPerformance *p = music_performance;
        music_performance = NULL;
        if (p) IDirectMusicPerformance_Release(p);
    }
    ReleaseSRWLockExclusive(&music_lock);
}
#ifdef REA_AUDIO_TEST
REA_API LONG REA_CALL REA_TestMusicLastResult(void) {
    return InterlockedCompareExchange(&music_last_result, 0, 0);
}
#endif
