#include "rea_audio_api.h"

/* Deliberately independent from WinMM device and endpoint volume controls. */
static SRWLOCK rea_settings_lock = SRWLOCK_INIT;
static BOOL rea_settings_initialized = FALSE;
static float rea_settings_gain[REA_AUDIO_VOLUME_COUNT] = {0.5f, 0.5f, 0.5f};
static const wchar_t *const rea_settings_names[REA_AUDIO_VOLUME_COUNT] = {
    L"SoundVolume", L"WaveVolume", L"CDVolume"
};

#ifdef REA_AUDIO_TEST
static wchar_t rea_settings_test_key[128];
static BOOL rea_settings_test_bound = FALSE;
#else
static const wchar_t rea_settings_key[] = L"Software\\Russobit\\Brother";
#endif

static float rea_normalize_gain(float value)
{
    union { float value; unsigned bits; } repr;
    repr.value = value;
    /* NaNs and infinities have no meaningful persisted volume. */
    if ((repr.bits & 0x7f800000u) == 0x7f800000u) return 0.5f;
    if (value < 0.0f) return 0.0f;
    if (value > 1.0f) return 1.0f;
    /* Normalize negative zero for stable persistence and comparisons. */
    return value == 0.0f ? 0.0f : value;
}

static const wchar_t *rea_registry_key_locked(void)
{
#ifdef REA_AUDIO_TEST
    return rea_settings_test_bound ? rea_settings_test_key : NULL;
#else
    return rea_settings_key;
#endif
}

/* Caller holds the exclusive settings lock. No device or backend calls. */
static void rea_load_settings_locked(void)
{
    const wchar_t *path;
    HKEY key;
    unsigned i;
    if (rea_settings_initialized) return;
    path = rea_registry_key_locked();
    if (path != NULL &&
        RegOpenKeyExW(HKEY_CURRENT_USER, path, 0, KEY_QUERY_VALUE, &key) == ERROR_SUCCESS) {
        for (i = 0; i < REA_AUDIO_VOLUME_COUNT; ++i) {
            DWORD type = 0;
            DWORD size = sizeof(float);
            float value = 0.5f;
            LSTATUS status = RegQueryValueExW(key, rea_settings_names[i], NULL,
                                             &type, (BYTE *)&value, &size);
            if (status == ERROR_SUCCESS && type == REG_BINARY && size == sizeof(float)) {
                rea_settings_gain[i] = rea_normalize_gain(value);
            }
        }
        RegCloseKey(key);
    }
    rea_settings_initialized = TRUE;
}

static void rea_ensure_settings_loaded(void)
{
    BOOL ready;
    AcquireSRWLockShared(&rea_settings_lock);
    ready = rea_settings_initialized;
    ReleaseSRWLockShared(&rea_settings_lock);
    if (ready) return;
    AcquireSRWLockExclusive(&rea_settings_lock);
    rea_load_settings_locked();
    ReleaseSRWLockExclusive(&rea_settings_lock);
}

REA_AUDIO_EXPORT float REA_AUDIO_CALL REA_GetVolume(unsigned kind)
{
    float value;
    if (kind >= REA_AUDIO_VOLUME_COUNT) return 0.5f;
    rea_ensure_settings_loaded();
    AcquireSRWLockShared(&rea_settings_lock);
    value = rea_settings_gain[kind];
    ReleaseSRWLockShared(&rea_settings_lock);
    return value;
}

void REA_AUDIO_CALL REA_ReadGains(float out[REA_AUDIO_VOLUME_COUNT])
{
    unsigned i;
    if (out == NULL) return;
    rea_ensure_settings_loaded();
    AcquireSRWLockShared(&rea_settings_lock);
    for (i = 0; i < REA_AUDIO_VOLUME_COUNT; ++i) out[i] = rea_settings_gain[i];
    ReleaseSRWLockShared(&rea_settings_lock);
}

REA_AUDIO_EXPORT void REA_AUDIO_CALL REA_SetVolume(unsigned kind, float gain)
{
    const wchar_t *path;
    HKEY key;
    DWORD disposition;
    if (kind >= REA_AUDIO_VOLUME_COUNT) return;
    gain = rea_normalize_gain(gain);
    rea_ensure_settings_loaded();
    AcquireSRWLockExclusive(&rea_settings_lock);
    rea_settings_gain[kind] = gain;
    path = rea_registry_key_locked();
    if (path != NULL &&
        RegCreateKeyExW(HKEY_CURRENT_USER, path, 0, NULL, 0, KEY_SET_VALUE,
                        NULL, &key, &disposition) == ERROR_SUCCESS) {
        RegSetValueExW(key, rea_settings_names[kind], 0, REG_BINARY,
                       (const BYTE *)&gain, sizeof(gain));
        RegCloseKey(key);
    }
    ReleaseSRWLockExclusive(&rea_settings_lock);
    /* The engine may call REA_ReadGains while holding its own backend lock. */
    REA_ApplyGains();
}

#ifdef REA_AUDIO_TEST
REA_AUDIO_EXPORT BOOL REA_AUDIO_CALL REA_TestSetRegistryKey(const wchar_t *key)
{
    static const wchar_t prefix[] = L"Software\\Russobit\\Brother\\REA_Audio_Test_";
    wchar_t expected[128];
    wchar_t reverse_digits[10];
    DWORD pid = GetCurrentProcessId();
    unsigned pos = 0, count = 0, i;
    BOOL accepted = FALSE;
    if (key == NULL) return FALSE;
    while (prefix[pos] != L'\0') {
        expected[pos] = prefix[pos];
        ++pos;
    }
    do {
        reverse_digits[count++] = (wchar_t)(L'0' + pid % 10);
        pid /= 10;
    } while (pid != 0);
    while (count != 0) expected[pos++] = reverse_digits[--count];
    expected[pos] = L'\0';
    /* Bounded exact comparison also rejects suffixes and unrelated keys. */
    for (i = 0; i <= pos; ++i) {
        if (key[i] != expected[i]) return FALSE;
    }
    AcquireSRWLockExclusive(&rea_settings_lock);
    if (!rea_settings_initialized && !rea_settings_test_bound) {
        for (i = 0; i <= pos; ++i) rea_settings_test_key[i] = expected[i];
        rea_settings_test_bound = TRUE;
        accepted = TRUE;
    }
    ReleaseSRWLockExclusive(&rea_settings_lock);
    return accepted;
}
#endif
