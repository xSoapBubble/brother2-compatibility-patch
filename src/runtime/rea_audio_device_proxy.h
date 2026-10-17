#ifndef REA_AUDIO_DEVICE_PROXY_H
#define REA_AUDIO_DEVICE_PROXY_H
#include <windows.h>
#include <mmsystem.h>
#include <dsound.h>
#ifdef __cplusplus
extern "C" {
#endif
__declspec(dllexport) HRESULT __cdecl REA_DirectSoundCreate(LPCGUID device,IDirectSound** result,IUnknown* outer);
#ifdef REA_AUDIO_TEST
// Mark only our proxy lost. No physical device changes. A normal next call
// attempts a new backend generation; ForceLoss clears the 250ms retry deadline.
__declspec(dllexport) HRESULT __cdecl REA_TestDeviceForceLoss(void* device);
// One-shot staging failure afterStep0=fresh device,1+=groups/voices. <0 disarms.
__declspec(dllexport) HRESULT __cdecl REA_TestDeviceFailNextRebuild(void* device,LONG afterStep,HRESULT failure);
// 0 generation,1 attempts,2 successes,3 failures,4 pending,5 live wrappers,
// 6 groups,7 PCM bytes,8 last HRESULT,9 active locks,10 native Play calls,
// 11 successful native notification registrations,12 staged group creates.
__declspec(dllexport) ULONG __cdecl REA_TestDeviceStatus(void* device,unsigned index);
__declspec(dllexport) HRESULT __cdecl REA_TestProxyReadNativePCM(void* buffer,ULONG offset,void* output,ULONG bytes);
__declspec(dllexport) HRESULT __cdecl REA_TestProxyNativeStatus(void* buffer,ULONG* status);
__declspec(dllexport) HRESULT __cdecl REA_TestProxyNativeCursor(void* buffer,ULONG* play,ULONG* write);
__declspec(dllexport) HRESULT __cdecl REA_TestProxyNativeVolume(void* buffer,LONG* value);
__declspec(dllexport) HRESULT __cdecl REA_TestProxyNativePan(void* buffer,LONG* value);
__declspec(dllexport) HRESULT __cdecl REA_TestProxyNativeFrequency(void* buffer,ULONG* value);
__declspec(dllexport) HRESULT __cdecl REA_TestProxyNative3DParameters(void* interfacePointer,void* parameters,ULONG isListener);
// Async monitor input oracle only: does not set pending or change any device.
// NULL clears override. Wait observed GUID via RouteGUIDs, then normal COM calls.
__declspec(dllexport) HRESULT __cdecl REA_TestDeviceSetRoute(void* device,const GUID* mapped,DWORD state);
// Same callback/filter pipeline: relevant ACTIVE/format/default=0/1/2,
// unrelated state/communications default/unrelated property=3/4/5.
__declspec(dllexport) HRESULT __cdecl REA_TestDeviceRouteEvent(void* device,unsigned kind);
__declspec(dllexport) HRESULT __cdecl REA_TestDeviceRouteGUIDs(void* device,GUID* accepted,GUID* observed);
// 0 ready,1 observed epoch,2 accepted epoch,3 callbacks,4 relevant events,
// 5 polls,6 mapped HRESULT,7 endpoint state,8 last reason flags,9 ignored,
// 10 monitor COM/init HRESULT. Reads do not trigger recovery.
__declspec(dllexport) ULONG __cdecl REA_TestDeviceRouteStatus(void* device,unsigned index);
#endif
#ifdef __cplusplus
}
#endif
#endif
