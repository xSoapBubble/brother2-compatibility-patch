#ifndef REA_AUDIO_API_H
#define REA_AUDIO_API_H

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0600
#endif
#include <windows.h>

#ifdef __cplusplus
extern "C" {
#endif

#define REA_AUDIO_EXPORT __declspec(dllexport)
#define REA_AUDIO_CALL __cdecl
/* Short aliases shared with the engine implementation. */
#define REA_API REA_AUDIO_EXPORT
#define REA_CALL REA_AUDIO_CALL

enum REA_AudioVolumeKind {
    REA_AUDIO_SOUND = 0,
    REA_AUDIO_WAVE = 1,
    REA_AUDIO_MUSIC = 2,
    REA_AUDIO_VOLUME_COUNT = 3
};

/* These APIs are called after DLL initialization, never from DllMain. */
REA_AUDIO_EXPORT void REA_AUDIO_CALL REA_SetVolume(unsigned kind, float gain);
REA_AUDIO_EXPORT float REA_AUDIO_CALL REA_GetVolume(unsigned kind);

/* Copies UI sound/legacy wave/UI music together; caller provides three floats. */
void REA_AUDIO_CALL REA_ReadGains(float out[REA_AUDIO_VOLUME_COUNT]);

/* Implemented by rea_audio_engine.c. No settings lock is held on this call. */
void REA_AUDIO_CALL REA_ApplyGains(void);

/* Engine-owned lifetime tracking; authoredDb is the game's original DS gain. */
REA_AUDIO_EXPORT void REA_AUDIO_CALL REA_TrackSound(void *owner, void *dsBuffer,
                                                   LONG authoredDb);
REA_AUDIO_EXPORT void REA_AUDIO_CALL REA_RemoveSound(void *owner);

#ifdef REA_AUDIO_TEST
/* Only the exact current-process test key is accepted, before first use.
 * The test build refuses all settings I/O until this binding succeeds.
 * This function and behavior do not exist in the production build. */
REA_AUDIO_EXPORT BOOL REA_AUDIO_CALL REA_TestSetRegistryKey(const wchar_t *key);
#endif

#ifdef __cplusplus
}
#endif
#endif
