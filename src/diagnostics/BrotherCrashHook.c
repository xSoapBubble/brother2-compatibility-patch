#define WIN32_LEAN_AND_MEAN
#define _WIN32_WINNT 0x0601
#include <windows.h>
#include <stddef.h>

/* x86 only. IPC is created by the launcher, never by this DLL. */
#if !defined(_M_IX86) && !defined(__i386__)
#error BrotherCrashHook requires x86
#endif
#define DIAG_MAGIC 0x42444941u
#define DIAG_VERSION 1u
#define DIAG_MAPPING_SIZE 4096u
#define DIAG_WAIT_MS 5000u

typedef struct DiagShared {
    DWORD magic, version, pid, tid;
    DWORD exceptionCode, exceptionAddress, exceptionFlags, remoteExceptionPointers;
    volatile LONG sequence;
    volatile DWORD reserved; /* Monitor acknowledgement sequence, offset36. */
} DiagShared;
_Static_assert(sizeof(void *) == 4, "remote pointer contract requires x86");
_Static_assert(sizeof(DiagShared) == 40, "IPC header size");
_Static_assert(offsetof(DiagShared, remoteExceptionPointers) == 28, "IPC pointers offset");
_Static_assert(offsetof(DiagShared, sequence) == 32, "IPC sequence offset");

static HMODULE g_module;
static HANDLE g_mapping, g_crash, g_done;
static DiagShared *g_shared;
static PVOID g_veh;
static volatile LONG g_init; /* 0 unused, 1 initializing, 2 ready, 3 disabled */
static volatile LONG g_busy;
static EXCEPTION_RECORD g_record;
static CONTEXT g_context __attribute__((aligned(16)));
static EXCEPTION_POINTERS g_pointers;

/* Volatile byte copy deliberately avoids a CRT memcpy or stack-sized locals. */
static void copy_bytes(volatile BYTE *dst, const volatile BYTE *src, SIZE_T count)
{
    while (count--) *dst++ = *src++;
}

static BOOL serious(DWORD code)
{
    switch (code) {
    case 0xc0000005u: /* access violation */
    case 0xc0000006u: /* in-page error */
    case 0xc000001du: /* illegal instruction */
    case 0xc0000094u: /* integer divide by zero */
    case 0xc0000095u: /* integer overflow */
    case 0xc00000fdu: /* stack overflow: best effort only */
    case 0xc0000374u: /* heap corruption: may bypass VEH */
    case 0xc0000409u: /* security/fastfail: real int29 bypasses VEH */
    case 0xc0000025u: /* noncontinuable exception violation */
    case 0xc0000026u: /* invalid exception disposition */
    case 0xc000008cu: /* array bounds exceeded */
    case 0xc000008eu: /* floating divide by zero */
    case 0xc0000090u: /* floating invalid operation */
    case 0xc0000091u: /* floating overflow */
    case 0xc0000092u: /* floating stack check */
        return TRUE;
    default:
        /* Deliberately excludes C++ E06D7363, breakpoints and single-step. */
        return FALSE;
    }
}

static LONG CALLBACK on_exception(EXCEPTION_POINTERS *ep)
{
    LONG committed;
    DWORD started, savedError;
    BOOL acknowledged = FALSE;
    if (g_init != 2 || !ep || !ep->ExceptionRecord || !ep->ContextRecord ||
        !serious(ep->ExceptionRecord->ExceptionCode)) return EXCEPTION_CONTINUE_SEARCH;
    if (InterlockedCompareExchange(&g_busy, 1, 0) != 0) return EXCEPTION_CONTINUE_SEARCH;
    savedError = GetLastError();

    /* Consume a stale acknowledgement left after a preceding timeout. */
    WaitForSingleObject(g_done, 0);
    copy_bytes((volatile BYTE *)&g_record, (const volatile BYTE *)ep->ExceptionRecord,
               sizeof(g_record));
    copy_bytes((volatile BYTE *)&g_context, (const volatile BYTE *)ep->ContextRecord,
               sizeof(g_context));
    g_pointers.ExceptionRecord = &g_record;
    g_pointers.ContextRecord = &g_context;
    g_shared->pid = GetCurrentProcessId();
    g_shared->tid = GetCurrentThreadId();
    g_shared->exceptionCode = g_record.ExceptionCode;
    g_shared->exceptionAddress = (DWORD)(ULONG_PTR)g_record.ExceptionAddress;
    g_shared->exceptionFlags = g_record.ExceptionFlags;
    g_shared->remoteExceptionPointers = (DWORD)(ULONG_PTR)&g_pointers;
    /* Interlocked commit publishes all preceding shared writes. */
    committed = InterlockedIncrement(&g_shared->sequence);
    started = GetTickCount();
    if (SetEvent(g_crash)) {
        for (;;) {
            DWORD elapsed = GetTickCount() - started; /* Wrap-safe unsigned delta. */
            if (elapsed >= DIAG_WAIT_MS) break;
            if (WaitForSingleObject(g_done, DIAG_WAIT_MS - elapsed) != WAIT_OBJECT_0) break;
            /* A late Done for an earlier timed-out fault cannot release this one. */
            if ((DWORD)InterlockedCompareExchange((volatile LONG *)&g_shared->reserved,
                                                  0, 0) == (DWORD)committed) {
                acknowledged = TRUE;
                break;
            }
        }
    }
    /* Without acknowledgement the monitor may still be reading these copies.
       Keep them immutable for the rest of this process and never pause again. */
    if (acknowledged) InterlockedExchange(&g_busy, 0);
    SetLastError(savedError);
    return EXCEPTION_CONTINUE_SEARCH;
}

static void close_ipc(void)
{
    if (g_shared) { UnmapViewOfFile(g_shared); g_shared = NULL; }
    if (g_mapping) { CloseHandle(g_mapping); g_mapping = NULL; }
    if (g_crash) { CloseHandle(g_crash); g_crash = NULL; }
    if (g_done) { CloseHandle(g_done); g_done = NULL; }
}

static BOOL token_ok(const WCHAR *token, DWORD n)
{
    if (n < 32 || n > 38) return FALSE;
    for (DWORD i = 0; i < n; ++i) {
        WCHAR c = token[i];
        if (!((c >= L'0' && c <= L'9') || (c >= L'a' && c <= L'f') ||
              (c >= L'A' && c <= L'F') || c == L'-' || c == L'{' || c == L'}'))
            return FALSE;
    }
    return TRUE;
}

static void make_name(WCHAR *dst, const WCHAR *token, const WCHAR *suffix)
{
    const WCHAR *prefix = L"Local\\BrotherDiag-";
    while (*prefix) *dst++ = *prefix++;
    while (*token) *dst++ = *token++;
    while (*suffix) *dst++ = *suffix++;
    *dst = 0;
}

/* Exported by .def with exact undecorated names; remote-thread compatible ABI. */
DWORD WINAPI DIAG_GetVersion(void) { return DIAG_VERSION; }

DWORD WINAPI DIAG_Initialize(LPVOID unused)
{
    WCHAR token[64], name[96];
    HMODULE pinned;
    DWORD n;
    LONG previous;
    (void)unused;
    previous = InterlockedCompareExchange(&g_init, 1, 0);
    if (previous != 0) return previous == 2 ? 1 : 0;

    n = GetEnvironmentVariableW(L"BROTHER_DIAG_TOKEN", token, 64);
    if (!n || n >= 64 || !token_ok(token, n)) goto disabled;
    make_name(name, token, L"");
    g_mapping = OpenFileMappingW(FILE_MAP_READ | FILE_MAP_WRITE, FALSE, name);
    if (!g_mapping) goto disabled;
    g_shared = (DiagShared *)MapViewOfFile(g_mapping, FILE_MAP_READ | FILE_MAP_WRITE,
                                         0, 0, DIAG_MAPPING_SIZE);
    if (!g_shared || g_shared->magic != DIAG_MAGIC || g_shared->version != DIAG_VERSION ||
        g_shared->pid != GetCurrentProcessId()) goto disabled;
    make_name(name, token, L"-Crash");
    g_crash = OpenEventW(EVENT_MODIFY_STATE, FALSE, name);
    if (!g_crash) goto disabled;
    make_name(name, token, L"-Done");
    g_done = OpenEventW(SYNCHRONIZE, FALSE, name);
    if (!g_done) goto disabled;

    /* Outside loader lock. The registered code cannot disappear on FreeLibrary. */
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                           GET_MODULE_HANDLE_EX_FLAG_PIN,
                           (LPCWSTR)(ULONG_PTR)&DIAG_Initialize, &pinned)) goto disabled;
    g_veh = AddVectoredExceptionHandler(1, on_exception);
    if (!g_veh) goto disabled;
    InterlockedExchange(&g_init, 2);
    return 1;

disabled:
    close_ipc();
    InterlockedExchange(&g_init, 3);
    return 0; /* Missing monitor/token is deliberately harmless. */
}

BOOL WINAPI DllMain(HINSTANCE module, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) g_module = module;
    /* Pinned after successful init. At process exit, the OS reclaims handles and
       address space; no waits, loader activity or unsafe handler teardown here. */
    return TRUE;
}
