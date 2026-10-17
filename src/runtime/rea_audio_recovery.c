#include "rea_audio_api.h"
#include <string.h>

/* Only the game's IDirectSound3DListener setters use this adapter. Its primary
 * buffer is an ordinary mixer output, not an application-filled PCM buffer.
 * QI(primary), Restore and Release preserve the original listener/secondary
 * objects and Windows' native default-device stream routing. */
typedef HRESULT (WINAPI *REC_Query)(void *, const GUID *, void **);
typedef ULONG (WINAPI *REC_Release)(void *);
typedef HRESULT (WINAPI *REC_Restore)(void *);
typedef HRESULT (WINAPI *REC_Call2)(void *, DWORD, DWORD);
typedef HRESULT (WINAPI *REC_Call4)(void *, DWORD, DWORD, DWORD, DWORD);
typedef HRESULT (WINAPI *REC_Call7)(void *, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD);

#define REC_BUFFERLOST ((HRESULT)0x88780096L)
#define REC_RETRY_MS 100u
static const GUID rec_iid_buffer = {0x279afa85,0x4981,0x11ce,{0xa5,0x21,0x00,0x20,0xaf,0x0b,0xe5,0x60}};
static SRWLOCK rec_lock = SRWLOCK_INIT;
static void *rec_listener;
static DWORD rec_values[5][7];
static unsigned rec_known, rec_pending;
static ULONGLONG rec_last_attempt;
static BOOL rec_attempted;
static ULONG rec_calls, rec_losses, rec_attempts, rec_restored, rec_deferred, rec_replayed;
static HRESULT rec_last_restore, rec_last_retry;

/* These slots are the five REA-proven listener setters. Float arguments are
 * copied as raw DWORDs; no floating conversion, rounding or ownership change. */
static unsigned rec_arg_count(unsigned slot)
{
    if (slot == 11 || slot == 12 || slot == 15) return 2;
    if (slot == 13) return 7;
    if (slot == 14) return 4;
    return 0;
}
static HRESULT rec_invoke(void *listener, unsigned slot, const DWORD *args)
{
    void **vtable = *(void ***)listener;
    unsigned n = rec_arg_count(slot);
    if (n == 2) return ((REC_Call2)vtable[slot])(listener,args[0],args[1]);
    if (n == 4) return ((REC_Call4)vtable[slot])(listener,args[0],args[1],args[2],args[3]);
    return ((REC_Call7)vtable[slot])(listener,args[0],args[1],args[2],args[3],args[4],args[5],args[6]);
}
static HRESULT rec_restore_primary(void *listener)
{
    void **vt = *(void ***)listener;
    void *primary = NULL;
    HRESULT hr = ((REC_Query)vt[0])(listener,&rec_iid_buffer,&primary);
    if (FAILED(hr)) return hr;
    if (primary == NULL) return E_NOINTERFACE;
    vt = *(void ***)primary;
    hr = ((REC_Restore)vt[20])(primary);
    ((REC_Release)vt[2])(primary);
    return hr;
}

REA_AUDIO_EXPORT HRESULT REA_AUDIO_CALL REA_ListenerCall(void *listener,
        unsigned slot, const DWORD *args, unsigned count)
{
    unsigned index, bit, i;
    HRESULT hr, replay;
    ULONGLONG now;
    if (listener == NULL || args == NULL || !rec_arg_count(slot) || count != rec_arg_count(slot))
        return E_INVALIDARG;
    index = slot - 11; bit = 1u << index;
    AcquireSRWLockExclusive(&rec_lock);
    ++rec_calls;
    if (rec_listener != listener) {
        rec_listener = listener;
        rec_known = rec_pending = 0;
        rec_attempted = FALSE;
    }
    memcpy(rec_values[index],args,count*sizeof(DWORD));
    rec_known |= bit;
    hr = rec_invoke(listener,slot,args);
    if (hr == REC_BUFFERLOST) {
        ++rec_losses;
        rec_pending |= bit;
        now = GetTickCount64();
        if (!rec_attempted || now - rec_last_attempt >= REC_RETRY_MS) {
            rec_last_attempt = now; rec_attempted = TRUE;
            ++rec_attempts;
            rec_last_restore = rec_restore_primary(listener);
            if (SUCCEEDED(rec_last_restore)) {
                ++rec_restored;
                /* Restore can reset listener state. Replay only properties
                 * observed on this same object, preserving current values. */
                rec_pending |= rec_known;
                hr = rec_invoke(listener,slot,args);
                rec_last_retry = hr;
            }
        }
    }
    if (SUCCEEDED(hr)) {
        rec_pending &= ~bit;
        /* A successful current setter also acts as a recovery heartbeat:
         * retry one-shot distance/doppler/rolloff settings after routing. */
        for (i = 0; i != 5; ++i) if ((rec_pending & (1u << i)) != 0) {
            replay = rec_invoke(listener,i+11,rec_values[i]);
            ++rec_replayed;
            if (SUCCEEDED(replay)) rec_pending &= ~(1u << i);
            else if (replay != REC_BUFFERLOST) {
                /* Preserve unrelated errors from deferred original setters. */
                hr = replay; break;
            }
        }
    }
    if (hr == REC_BUFFERLOST) {
        ++rec_deferred;
        hr = S_OK; /* device still absent: retain latest request, retry later */
    }
    ReleaseSRWLockExclusive(&rec_lock);
    return hr;
}

/* Called before the native allocator releases its listener, including when a
 * new COM object might subsequently reuse the same address. No AddRef is held. */
REA_AUDIO_EXPORT void REA_AUDIO_CALL REA_ForgetListener(void *listener)
{
    AcquireSRWLockExclusive(&rec_lock);
    if (rec_listener == listener) {
        rec_listener = NULL; rec_known = rec_pending = 0; rec_attempted = FALSE;
    }
    ReleaseSRWLockExclusive(&rec_lock);
}

REA_AUDIO_EXPORT ULONG REA_AUDIO_CALL REA_GetRecoveryStatus(unsigned index)
{
    ULONG n=0;
    AcquireSRWLockShared(&rec_lock);
    switch(index) {
    case 0:n=rec_calls;break; case 1:n=rec_losses;break;
    case 2:n=rec_attempts;break; case 3:n=rec_restored;break;
    case 4:n=rec_deferred;break; case 5:n=rec_replayed;break;
    case 6:n=(ULONG)rec_last_restore;break; case 7:n=(ULONG)rec_last_retry;break;
    case 8:n=rec_pending;break; case 9:n=rec_known;break;
    }
    ReleaseSRWLockShared(&rec_lock);
    return n;
}
