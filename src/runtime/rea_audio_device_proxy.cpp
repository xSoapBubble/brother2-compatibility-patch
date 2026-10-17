// Stable DirectSound COM identities with transactional default-device recovery.
// Only this translation unit owns native device/buffer/interface references.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <mmsystem.h>
#include <dsound.h>
#include <mmdeviceapi.h>
#include <propvarutil.h>
#include <new>
#include <string.h>
#include <math.h>

static const GUID gUnknown={0,0,0,{0xc0,0,0,0,0,0,0,0x46}};
static const GUID gDevice={0x279afa83,0x4981,0x11ce,{0xa5,0x21,0,0x20,0xaf,0x0b,0xe5,0x60}};
static const GUID gListener={0x279afa84,0x4981,0x11ce,{0xa5,0x21,0,0x20,0xaf,0x0b,0xe5,0x60}};
static const GUID gBuffer={0x279afa85,0x4981,0x11ce,{0xa5,0x21,0,0x20,0xaf,0x0b,0xe5,0x60}};
static const GUID gThree={0x279afa86,0x4981,0x11ce,{0xa5,0x21,0,0x20,0xaf,0x0b,0xe5,0x60}};
static const GUID gNotify={0xb0210783,0x89cd,0x11d0,{0xaf,0x08,0,0xa0,0xc9,0x25,0xcd,0x16}};
static const GUID gDefault={0xdef00000,0x9c6d,0x47ed,{0xaa,0xf1,0x4d,0xda,0x8f,0x2b,0x5c,0x03}};
static bool eq(REFGUID a,REFGUID b){return memcmp(&a,&b,sizeof(GUID))==0;}
template<class T> static void drop(T*& p){if(p){p->Release();p=0;}}
static void* alloc(SIZE_T n){return n?HeapAlloc(GetProcessHeap(),HEAP_ZERO_MEMORY,n):0;}
static void dealloc(void* p){if(p)HeapFree(GetProcessHeap(),0,p);}
typedef HRESULT (WINAPI *CreateDS)(LPCGUID,LPDIRECTSOUND*,LPUNKNOWN);
static INIT_ONCE factoryOnce=INIT_ONCE_STATIC_INIT;
static CreateDS nativeFactory;
typedef HRESULT (WINAPI *GetDSID)(LPCGUID,LPGUID);
static GetDSID nativeGetDeviceID;
static BOOL CALLBACK loadFactory(PINIT_ONCE,PVOID,PVOID*){
 WCHAR path[MAX_PATH];UINT n=GetSystemDirectoryW(path,MAX_PATH);
 if(n && n<MAX_PATH-12){memcpy(path+n,L"\\dsound.dll",12*sizeof(WCHAR));HMODULE m=LoadLibraryW(path);if(m){nativeFactory=(CreateDS)(void*)GetProcAddress(m,"DirectSoundCreate");nativeGetDeviceID=(GetDSID)(void*)GetProcAddress(m,"GetDeviceID");}}return TRUE;
}
static HRESULT createNative(IDirectSound** p){InitOnceExecuteOnce(&factoryOnce,loadFactory,0,0);return nativeFactory?nativeFactory(0,p,0):DSERR_NODRIVER;}
static HRESULT mappedDefault(GUID* guid){memset(guid,0,sizeof(*guid));InitOnceExecuteOnce(&factoryOnce,loadFactory,0,0);return nativeGetDeviceID?nativeGetDeviceID(&gDefault,guid):E_NOTIMPL;}
struct Device;struct Buffer;struct Relay;struct Monitor;
struct Guard { CRITICAL_SECTION* p;Guard(CRITICAL_SECTION& c):p(&c){EnterCriticalSection(p);}~Guard(){LeaveCriticalSection(p);} };
struct Group {
 Group* next;Device* device;unsigned refs;DSBUFFERDESC desc;BYTE* format;DWORD formatBytes;BYTE* pcm;
 IDirectSoundBuffer* proto;IDirectSoundBuffer* stage;Buffer* locked;bool primary,formatSet;
 Group():next(0),device(0),refs(0),format(0),formatBytes(0),pcm(0),proto(0),stage(0),locked(0),primary(false),formatSet(false){memset(&desc,0,sizeof(desc));}
 ~Group(){drop(proto);drop(stage);dealloc(format);dealloc(pcm);}
};
struct Listener:IDirectSound3DListener {
 Buffer* owner;DS3DLISTENER state,deferred;bool dirty;DWORD dirtyMask;HRESULT apply(LPCDS3DLISTENER,DWORD,DWORD);
 Listener(Buffer* b);HRESULT STDMETHODCALLTYPE QueryInterface(REFIID,void**);ULONG STDMETHODCALLTYPE AddRef();ULONG STDMETHODCALLTYPE Release();
 HRESULT STDMETHODCALLTYPE GetAllParameters(LPDS3DLISTENER);HRESULT STDMETHODCALLTYPE GetDistanceFactor(LPD3DVALUE);HRESULT STDMETHODCALLTYPE GetDopplerFactor(LPD3DVALUE);HRESULT STDMETHODCALLTYPE GetOrientation(LPD3DVECTOR,LPD3DVECTOR);HRESULT STDMETHODCALLTYPE GetPosition(LPD3DVECTOR);HRESULT STDMETHODCALLTYPE GetRolloffFactor(LPD3DVALUE);HRESULT STDMETHODCALLTYPE GetVelocity(LPD3DVECTOR);
 HRESULT STDMETHODCALLTYPE SetAllParameters(LPCDS3DLISTENER,DWORD);HRESULT STDMETHODCALLTYPE SetDistanceFactor(D3DVALUE,DWORD);HRESULT STDMETHODCALLTYPE SetDopplerFactor(D3DVALUE,DWORD);HRESULT STDMETHODCALLTYPE SetOrientation(D3DVALUE,D3DVALUE,D3DVALUE,D3DVALUE,D3DVALUE,D3DVALUE,DWORD);HRESULT STDMETHODCALLTYPE SetPosition(D3DVALUE,D3DVALUE,D3DVALUE,DWORD);HRESULT STDMETHODCALLTYPE SetRolloffFactor(D3DVALUE,DWORD);HRESULT STDMETHODCALLTYPE SetVelocity(D3DVALUE,D3DVALUE,D3DVALUE,DWORD);HRESULT STDMETHODCALLTYPE CommitDeferredSettings();
};
struct Three:IDirectSound3DBuffer {
 Buffer* owner;DS3DBUFFER state,deferred;bool dirty;DWORD dirtyMask;HRESULT apply(LPCDS3DBUFFER,DWORD,DWORD);
 Three(Buffer* b);HRESULT STDMETHODCALLTYPE QueryInterface(REFIID,void**);ULONG STDMETHODCALLTYPE AddRef();ULONG STDMETHODCALLTYPE Release();
 HRESULT STDMETHODCALLTYPE GetAllParameters(LPDS3DBUFFER);HRESULT STDMETHODCALLTYPE GetConeAngles(LPDWORD,LPDWORD);HRESULT STDMETHODCALLTYPE GetConeOrientation(LPD3DVECTOR);HRESULT STDMETHODCALLTYPE GetConeOutsideVolume(LPLONG);HRESULT STDMETHODCALLTYPE GetMaxDistance(LPD3DVALUE);HRESULT STDMETHODCALLTYPE GetMinDistance(LPD3DVALUE);HRESULT STDMETHODCALLTYPE GetMode(LPDWORD);HRESULT STDMETHODCALLTYPE GetPosition(LPD3DVECTOR);HRESULT STDMETHODCALLTYPE GetVelocity(LPD3DVECTOR);
 HRESULT STDMETHODCALLTYPE SetAllParameters(LPCDS3DBUFFER,DWORD);HRESULT STDMETHODCALLTYPE SetConeAngles(DWORD,DWORD,DWORD);HRESULT STDMETHODCALLTYPE SetConeOrientation(D3DVALUE,D3DVALUE,D3DVALUE,DWORD);HRESULT STDMETHODCALLTYPE SetConeOutsideVolume(LONG,DWORD);HRESULT STDMETHODCALLTYPE SetMaxDistance(D3DVALUE,DWORD);HRESULT STDMETHODCALLTYPE SetMinDistance(D3DVALUE,DWORD);HRESULT STDMETHODCALLTYPE SetMode(DWORD,DWORD);HRESULT STDMETHODCALLTYPE SetPosition(D3DVALUE,D3DVALUE,D3DVALUE,DWORD);HRESULT STDMETHODCALLTYPE SetVelocity(D3DVALUE,D3DVALUE,D3DVALUE,DWORD);
};
struct Notify:IDirectSoundNotify {
 Buffer* owner;Notify(Buffer* b):owner(b){}HRESULT STDMETHODCALLTYPE QueryInterface(REFIID,void**);ULONG STDMETHODCALLTYPE AddRef();ULONG STDMETHODCALLTYPE Release();HRESULT STDMETHODCALLTYPE SetNotificationPositions(DWORD,LPCDSBPOSITIONNOTIFY);
};
struct Buffer final:IDirectSoundBuffer {
 LONG refs;Device* device;Group* group;Buffer* next;IDirectSoundBuffer *native,*stage;
 IDirectSound3DListener *nl,*sl;IDirectSound3DBuffer *nt,*st;IDirectSoundNotify *nn,*sn;
 Listener listener;Three three;Notify notify;bool haveListener,haveThree,haveNotify;
 LONG volume,pan;DWORD frequency,cursor,playFlags,playPriority;ULONGLONG cursorTime;bool wanted;
 DSBCAPS caps;DSBPOSITIONNOTIFY* positions;DWORD positionCount;
 DWORD lockOffset,lockBytes,lockFirst;void *lockA,*lockB;Relay *relay,*stageRelay,*retired;bool stagePlayed,stageExpired;
 Buffer(Device* d,Group* g);~Buffer();void cleanStage();HRESULT interfaces(IDirectSoundBuffer*,IDirectSound3DListener**,IDirectSound3DBuffer**,IDirectSoundNotify**);DWORD current(ULONGLONG,bool* =0);HRESULT seed();
 HRESULT STDMETHODCALLTYPE QueryInterface(REFIID,void**);ULONG STDMETHODCALLTYPE AddRef();ULONG STDMETHODCALLTYPE Release();
 HRESULT STDMETHODCALLTYPE GetCaps(LPDSBCAPS);HRESULT STDMETHODCALLTYPE GetCurrentPosition(LPDWORD,LPDWORD);HRESULT STDMETHODCALLTYPE GetFormat(LPWAVEFORMATEX,DWORD,LPDWORD);HRESULT STDMETHODCALLTYPE GetVolume(LPLONG);HRESULT STDMETHODCALLTYPE GetPan(LPLONG);HRESULT STDMETHODCALLTYPE GetFrequency(LPDWORD);HRESULT STDMETHODCALLTYPE GetStatus(LPDWORD);HRESULT STDMETHODCALLTYPE Initialize(LPDIRECTSOUND,LPCDSBUFFERDESC);
 HRESULT STDMETHODCALLTYPE Lock(DWORD,DWORD,LPVOID*,LPDWORD,LPVOID*,LPDWORD,DWORD);HRESULT STDMETHODCALLTYPE Play(DWORD,DWORD,DWORD);HRESULT STDMETHODCALLTYPE SetCurrentPosition(DWORD);HRESULT STDMETHODCALLTYPE SetFormat(LPCWAVEFORMATEX);HRESULT STDMETHODCALLTYPE SetVolume(LONG);HRESULT STDMETHODCALLTYPE SetPan(LONG);HRESULT STDMETHODCALLTYPE SetFrequency(DWORD);HRESULT STDMETHODCALLTYPE Stop();HRESULT STDMETHODCALLTYPE Unlock(LPVOID,DWORD,LPVOID,DWORD);HRESULT STDMETHODCALLTYPE Restore();
};
struct Device final:IDirectSound {
 LONG refs;CRITICAL_SECTION lock;IDirectSound* native;Buffer* buffers;Group* groups;HWND hwnd;DWORD coop,speakers;bool haveCoop,haveSpeakers,pending,rebuilding;ULONGLONG retryAt;
 DSCAPS caps;ULONG generation,attempts,successes,failures,playCalls,notifyCalls,groupCreates;HRESULT last;Relay* relays;HANDLE relayThread,relayStop,relayWake;
#ifdef REA_AUDIO_TEST
 LONG failStep;HRESULT failHr;
#endif
 Monitor* monitor;GUID acceptedMappedGuid,observedMappedGuid;HRESULT acceptedMapHr,observedMapHr;ULONG acceptedRouteEpoch,observedRouteEpoch;DWORD acceptedEndpointState,observedEndpointState,lastRouteReason;
 Device(IDirectSound* n,Monitor* observation,const GUID& initialGuid,HRESULT initialHr,ULONG initialEpoch,DWORD initialState):refs(1),native(n),buffers(0),groups(0),hwnd(0),coop(1),speakers(0),haveCoop(false),haveSpeakers(false),pending(false),rebuilding(false),retryAt(0),generation(1),attempts(0),successes(0),failures(0),playCalls(0),notifyCalls(0),groupCreates(0),last(S_OK),relays(0),relayThread(0),relayStop(0),relayWake(0){InitializeCriticalSection(&lock);memset(&caps,0,sizeof(caps));caps.dwSize=sizeof(caps);native->GetCaps(&caps);
#ifdef REA_AUDIO_TEST
 failStep=-1;failHr=E_FAIL;
#endif
 monitor=observation;acceptedMapHr=initialHr;acceptedMappedGuid=initialGuid;observedMappedGuid=acceptedMappedGuid;observedMapHr=acceptedMapHr;acceptedRouteEpoch=observedRouteEpoch=initialEpoch;acceptedEndpointState=observedEndpointState=initialState;lastRouteReason=0;
 }
 ~Device();bool startRelay();void attachRelay(Relay*);void detachRelay(Relay*);static DWORD WINAPI relayMain(void*);
 void mark(){pending=true;}bool recover();void before();
 template<class F> HRESULT call(F f){before();if(pending)return DSERR_BUFFERLOST;HRESULT hr=f();if(hr==DSERR_BUFFERLOST){mark();before();if(!pending){hr=f();if(hr==DSERR_BUFFERLOST)mark();}}return hr;}
 HRESULT mask(HRESULT hr){return hr==DSERR_BUFFERLOST?S_OK:hr;}
 bool injected(int step){
#ifdef REA_AUDIO_TEST
  if(failStep>=0&&step>=failStep){last=failHr;failStep=-1;return true;}
#else
  (void)step;
#endif
  return false;
 }
 HRESULT STDMETHODCALLTYPE QueryInterface(REFIID,void**);ULONG STDMETHODCALLTYPE AddRef(){return (ULONG)InterlockedIncrement(&refs);}ULONG STDMETHODCALLTYPE Release(){ULONG n=(ULONG)InterlockedDecrement(&refs);if(!n)delete this;return n;}
 HRESULT STDMETHODCALLTYPE CreateSoundBuffer(LPCDSBUFFERDESC,LPDIRECTSOUNDBUFFER*,LPUNKNOWN);HRESULT STDMETHODCALLTYPE GetCaps(LPDSCAPS);HRESULT STDMETHODCALLTYPE DuplicateSoundBuffer(LPDIRECTSOUNDBUFFER,LPDIRECTSOUNDBUFFER*);HRESULT STDMETHODCALLTYPE SetCooperativeLevel(HWND,DWORD);HRESULT STDMETHODCALLTYPE Compact();HRESULT STDMETHODCALLTYPE GetSpeakerConfig(LPDWORD);HRESULT STDMETHODCALLTYPE SetSpeakerConfig(DWORD);HRESULT STDMETHODCALLTYPE Initialize(LPCGUID){return DSERR_ALREADYINITIALIZED;}
};
// Endpoint observation is owned by a separate MTA. No MMDevice call, wait or
// monitor write lock runs on the game's camera/render thread or in callbacks.
static const GUID gMMEnumeratorClass={0xbcde0395,0xe52f,0x467c,{0x8e,0x3d,0xc4,0x57,0x92,0x91,0x69,0x2e}};
static const GUID gMMEnumerator={0xa95664d2,0x9614,0x4f35,{0xa7,0x46,0xde,0x8d,0xb6,0x36,0x17,0xe6}};
static const GUID gMMNotify={0x7991eec9,0x7e89,0x4d85,{0x83,0x90,0x6c,0x70,0x3c,0xec,0x60,0xc0}};
static const PROPERTYKEY kEndpointGuid={{0x1da5d803,0xd492,0x4edd,{0x8c,0x23,0xe0,0xc0,0xff,0xee,0x7f,0x0e}},4};
static const PROPERTYKEY kDeviceFormat={{0xf19f064d,0x082c,0x4e27,{0xbc,0x73,0x68,0x82,0xa1,0xbb,0x8e,0x4c}},0};
static const PROPERTYKEY kOEMFormat={{0xe4870e26,0x3cc5,0x4cd2,{0xba,0x46,0xca,0x0a,0x9a,0x70,0xed,0x04}},3};
static bool keyeq(const PROPERTYKEY& a,const PROPERTYKEY& b){return a.pid==b.pid&&eq(a.fmtid,b.fmtid);}
struct RouteSnapshot {GUID mapped;HRESULT mapHr;DWORD state,reason;ULONG epoch,polls,relevant;bool ready,injected;WCHAR id[512];};
struct RouteRecord {volatile LONG busy,ready;DWORD kind,state;WCHAR id[512];};
struct Monitor final:IMMNotificationClient {
 LONG refs;HANDLE thread,stop,wake;SRWLOCK snapshotLock;RouteSnapshot snapshot;RouteRecord records[32];volatile LONG writeIndex,callbacks,ignored,overflow;volatile LONG comHr;IMMDevice* cached;GUID cachedGuid;
#ifdef REA_AUDIO_TEST
 bool overrideEnabled;GUID overrideGuid;DWORD overrideState;
#endif
 Monitor():refs(1),thread(0),stop(0),wake(0),writeIndex(0),callbacks(0),ignored(0),overflow(0),comHr(E_PENDING),cached(0){InitializeSRWLock(&snapshotLock);memset(&snapshot,0,sizeof(snapshot));snapshot.mapHr=E_PENDING;memset(records,0,sizeof(records));memset(&cachedGuid,0,sizeof(cachedGuid));
#ifdef REA_AUDIO_TEST
 overrideEnabled=false;memset(&overrideGuid,0,sizeof(overrideGuid));overrideState=DEVICE_STATE_ACTIVE;
#endif
 }
 ~Monitor(){if(thread)CloseHandle(thread);if(stop)CloseHandle(stop);if(wake)CloseHandle(wake);}
 HRESULT STDMETHODCALLTYPE QueryInterface(REFIID id,void** p){if(!p)return E_POINTER;*p=0;if(eq(id,gUnknown)||eq(id,gMMNotify)){*p=(IMMNotificationClient*)this;AddRef();return S_OK;}return E_NOINTERFACE;}
 ULONG STDMETHODCALLTYPE AddRef(){return (ULONG)InterlockedIncrement(&refs);}ULONG STDMETHODCALLTYPE Release(){ULONG n=(ULONG)InterlockedDecrement(&refs);if(!n)delete this;return n;}
 void start(){stop=CreateEventW(0,TRUE,FALSE,0);wake=CreateEventW(0,FALSE,FALSE,0);if(stop&&wake)thread=CreateThread(0,0,main,this,0,0);if(!thread)InterlockedExchange(&comHr,E_OUTOFMEMORY);}
 void shutdown(){if(stop)SetEvent(stop);if(wake)SetEvent(wake);if(thread)WaitForSingleObject(thread,INFINITE);}
 bool read(RouteSnapshot* out){if(!TryAcquireSRWLockShared(&snapshotLock))return false;*out=snapshot;ReleaseSRWLockShared(&snapshotLock);return out->ready;}
 void record(DWORD kind,LPCWSTR id,DWORD state){InterlockedIncrement(&callbacks);LONG index=InterlockedIncrement(&writeIndex);RouteRecord* r=&records[((ULONG)index)%32];if(InterlockedCompareExchange(&r->busy,1,0)!=0){InterlockedExchange(&overflow,1);if(wake)SetEvent(wake);return;}if(r->ready)InterlockedExchange(&overflow,1);r->kind=kind;r->state=state;DWORD n=0;if(id)while(n<511&&id[n]){r->id[n]=id[n];++n;}r->id[n]=0;if(id&&n==511&&id[n])InterlockedExchange(&overflow,1);InterlockedExchange(&r->ready,1);InterlockedExchange(&r->busy,0);if(wake)SetEvent(wake);}
 HRESULT STDMETHODCALLTYPE OnDefaultDeviceChanged(EDataFlow flow,ERole role,LPCWSTR id){if(flow!=eRender||role==eCommunications){InterlockedIncrement(&callbacks);InterlockedIncrement(&ignored);return S_OK;}record(1,id,(DWORD)role);return S_OK;}
 HRESULT STDMETHODCALLTYPE OnDeviceStateChanged(LPCWSTR id,DWORD state){record(2,id,state);return S_OK;}
 HRESULT STDMETHODCALLTYPE OnDeviceAdded(LPCWSTR id){record(3,id,0);return S_OK;}
 HRESULT STDMETHODCALLTYPE OnDeviceRemoved(LPCWSTR id){record(4,id,0);return S_OK;}
 HRESULT STDMETHODCALLTYPE OnPropertyValueChanged(LPCWSTR id,const PROPERTYKEY key){if(!keyeq(key,kDeviceFormat)&&!keyeq(key,kOEMFormat)){InterlockedIncrement(&callbacks);InterlockedIncrement(&ignored);return S_OK;}record(5,id,0);return S_OK;}
 void query(IMMDeviceEnumerator* enumerator,RouteSnapshot* out){memset(out,0,sizeof(*out));out->mapHr=mappedDefault(&out->mapped);
#ifdef REA_AUDIO_TEST
  AcquireSRWLockShared(&snapshotLock);bool injected=overrideEnabled;GUID injection=overrideGuid;DWORD injectedState=overrideState;ReleaseSRWLockShared(&snapshotLock);if(injected){out->injected=true;out->mapped=injection;out->mapHr=S_OK;out->state=injectedState;lstrcpyW(out->id,L"test:");StringFromGUID2(injection,out->id+5,507);return;}
#endif
  if(FAILED(out->mapHr)||!enumerator)return;
  if(cached&&!eq(cachedGuid,out->mapped))drop(cached);
  if(cached){HRESULT hr=cached->GetState(&out->state);if(FAILED(hr))drop(cached);}
  if(!cached){IMMDeviceCollection* collection=0;HRESULT hr=enumerator->EnumAudioEndpoints(eRender,DEVICE_STATEMASK_ALL,&collection);if(SUCCEEDED(hr)){UINT count=0;collection->GetCount(&count);if(count>512)count=512;for(UINT i=0;i<count&&!cached;++i){IMMDevice* dev=0;if(FAILED(collection->Item(i,&dev)))continue;IPropertyStore* store=0;if(SUCCEEDED(dev->OpenPropertyStore(STGM_READ,&store))){PROPVARIANT value;PropVariantInit(&value);if(SUCCEEDED(store->GetValue(kEndpointGuid,&value))&&value.vt==VT_LPWSTR&&value.pwszVal){GUID guid;if(SUCCEEDED(CLSIDFromString(value.pwszVal,&guid))&&eq(guid,out->mapped)){cached=dev;cached->AddRef();cachedGuid=guid;cached->GetState(&out->state);}}PropVariantClear(&value);drop(store);}drop(dev);}drop(collection);}}
  if(cached){LPWSTR id=0;if(SUCCEEDED(cached->GetId(&id))){lstrcpynW(out->id,id,512);CoTaskMemFree(id);}}
 }
 void poll(IMMDeviceEnumerator* enumerator){RouteSnapshot next,old;AcquireSRWLockShared(&snapshotLock);old=snapshot;ReleaseSRWLockShared(&snapshotLock);query(enumerator,&next);DWORD reason=0;ULONG relevant=0;
  if(old.ready){if(old.mapHr!=next.mapHr)reason|=256;if(!eq(old.mapped,next.mapped))reason|=1;if(old.state!=next.state)reason|=2;if(lstrcmpW(old.id,next.id)!=0)reason|=4;}
  for(unsigned i=0;i<32;++i){RouteRecord local;RouteRecord* r=&records[i];if(InterlockedCompareExchange(&r->busy,1,0)!=0)continue;bool ready=r->ready!=0;if(ready){local.kind=r->kind;local.state=r->state;memcpy(local.id,r->id,sizeof(local.id));InterlockedExchange(&r->ready,0);}InterlockedExchange(&r->busy,0);if(!ready)continue;bool matches=local.id[0]&&((old.id[0]&&lstrcmpW(local.id,old.id)==0)||(next.id[0]&&lstrcmpW(local.id,next.id)==0));if(matches){++relevant;reason|=local.kind==1?16:(local.kind==5?32:(local.kind==2?8:64));}else InterlockedIncrement(&ignored);}
  if(InterlockedExchange(&overflow,0)){reason|=128;++relevant;}
  next.ready=true;next.epoch=old.ready?old.epoch+(reason?1:0):1+(relevant?1:0);next.polls=old.polls+1;next.relevant=old.relevant+relevant;next.reason=reason?reason:old.reason;
  AcquireSRWLockExclusive(&snapshotLock);snapshot=next;ReleaseSRWLockExclusive(&snapshotLock);
 }
 static DWORD WINAPI main(void* arg){Monitor* m=(Monitor*)arg;HRESULT init=CoInitializeEx(0,COINIT_MULTITHREADED);InterlockedExchange(&m->comHr,init);IMMDeviceEnumerator* enumerator=0;bool registered=false;if(SUCCEEDED(init)){HRESULT hr=CoCreateInstance(gMMEnumeratorClass,0,CLSCTX_INPROC_SERVER,gMMEnumerator,(void**)&enumerator);InterlockedExchange(&m->comHr,hr);if(SUCCEEDED(hr)){hr=enumerator->RegisterEndpointNotificationCallback(m);InterlockedExchange(&m->comHr,hr);registered=SUCCEEDED(hr);}}
  HANDLE events[2]={m->stop,m->wake};for(;;){m->poll(enumerator);DWORD wait=WaitForMultipleObjects(2,events,FALSE,500);if(wait==WAIT_OBJECT_0)break;}
  if(registered)enumerator->UnregisterEndpointNotificationCallback(m);drop(m->cached);drop(enumerator);if(SUCCEEDED(init))CoUninitialize();return 0;
 }
#ifdef REA_AUDIO_TEST
 HRESULT setRoute(const GUID* guid,DWORD state){AcquireSRWLockExclusive(&snapshotLock);overrideEnabled=guid!=0;if(guid)overrideGuid=*guid;overrideState=state;ReleaseSRWLockExclusive(&snapshotLock);if(wake)SetEvent(wake);return S_OK;}
 HRESULT testEvent(unsigned kind){RouteSnapshot s;if(!read(&s))return E_PENDING;switch(kind){case 0:return OnDeviceStateChanged(s.id,DEVICE_STATE_ACTIVE);case 1:return OnPropertyValueChanged(s.id,kDeviceFormat);case 2:return OnDefaultDeviceChanged(eRender,eConsole,s.id);case 3:return OnDeviceStateChanged(L"test:unrelated-device",DEVICE_STATE_ACTIVE);case 4:return OnDefaultDeviceChanged(eRender,eCommunications,s.id);case 5:{PROPERTYKEY volume={};return OnPropertyValueChanged(s.id,volume);}default:return E_INVALIDARG;}}
#endif
};
void Device::before(){
 if(!monitor&&buffers){monitor=new(std::nothrow) Monitor;if(monitor)monitor->start();}
 RouteSnapshot route;if(monitor&&monitor->read(&route)){observedMappedGuid=route.mapped;observedMapHr=route.mapHr;observedRouteEpoch=route.epoch;observedEndpointState=route.state;lastRouteReason=route.reason;
  bool same=acceptedMapHr==route.mapHr&&eq(acceptedMappedGuid,route.mapped);
  if(!acceptedRouteEpoch&&same&&route.epoch==1){acceptedRouteEpoch=route.epoch;acceptedEndpointState=route.state;}
  else if(!same||acceptedRouteEpoch!=route.epoch||acceptedEndpointState!=route.state)mark();
 }
 if(pending&&!rebuilding&&GetTickCount64()>=retryAt)recover();
}
Listener::Listener(Buffer* b):owner(b),dirty(false),dirtyMask(0){memset(&state,0,sizeof(state));state.dwSize=sizeof(state);state.vOrientFront.z=1;state.vOrientTop.y=1;state.flDistanceFactor=state.flRolloffFactor=state.flDopplerFactor=1;deferred=state;}
Three::Three(Buffer* b):owner(b),dirty(false),dirtyMask(0){memset(&state,0,sizeof(state));state.dwSize=sizeof(state);state.dwInsideConeAngle=state.dwOutsideConeAngle=360;state.vConeOrientation.z=1;state.flMinDistance=1;state.flMaxDistance=DS3D_DEFAULTMAXDISTANCE;deferred=state;}
Buffer::Buffer(Device* d,Group* g):refs(1),device(d),group(g),next(0),native(0),stage(0),nl(0),sl(0),nt(0),st(0),nn(0),sn(0),listener(this),three(this),notify(this),haveListener(false),haveThree(false),haveNotify(false),volume(0),pan(0),frequency(0),cursor(0),playFlags(0),playPriority(0),cursorTime(GetTickCount64()),wanted(false),positions(0),positionCount(0),lockOffset(0),lockBytes(0),lockFirst(0),lockA(0),lockB(0),relay(0),stageRelay(0),retired(0),stagePlayed(false),stageExpired(false){memset(&caps,0,sizeof(caps));caps.dwSize=sizeof(caps);caps.dwFlags=g->desc.dwFlags;caps.dwBufferBytes=g->desc.dwBufferBytes;if(g->format)frequency=((WAVEFORMATEX*)g->format)->nSamplesPerSec;}
struct Relay {
 LONG refs;Relay *next,*retiredNext;bool active,bound;ULONG generation;DWORD count;HANDLE* events;HANDLE* targets;DSBPOSITIONNOTIFY* nativePositions;
 Relay():refs(1),next(0),retiredNext(0),active(false),bound(false),generation(0),count(0),events(0),targets(0),nativePositions(0){}
 ~Relay(){for(DWORD i=0;i<count;++i){if(events&&events[i])CloseHandle(events[i]);if(targets&&targets[i])CloseHandle(targets[i]);}dealloc(events);dealloc(targets);dealloc(nativePositions);}
 void add(){InterlockedIncrement(&refs);}void release(){if(!InterlockedDecrement(&refs))delete this;}
};
static void releaseRelay(Relay*& r){if(r){r->release();r=0;}}
static void releaseRetired(Relay*& r){while(r){Relay* next=r->retiredNext;r->release();r=next;}}
static Relay* newRelay(DWORD n,LPCDSBPOSITIONNOTIFY p,Relay* retained=0){if(!n)return 0;Relay* r=new(std::nothrow) Relay;if(!r)return 0;r->count=n;r->events=(HANDLE*)alloc(n*sizeof(HANDLE));r->targets=(HANDLE*)alloc(n*sizeof(HANDLE));r->nativePositions=(DSBPOSITIONNOTIFY*)alloc(n*sizeof(DSBPOSITIONNOTIFY));if(!r->events||!r->targets||!r->nativePositions){delete r;return 0;}for(DWORD i=0;i<n;++i){r->events[i]=CreateEventW(0,FALSE,FALSE,0);if(!r->events[i]||!DuplicateHandle(GetCurrentProcess(),retained&&i<retained->count?retained->targets[i]:p[i].hEventNotify,GetCurrentProcess(),&r->targets[i],EVENT_MODIFY_STATE,FALSE,0)){delete r;return 0;}r->nativePositions[i].dwOffset=p[i].dwOffset;r->nativePositions[i].hEventNotify=r->events[i];}return r;}
bool Device::startRelay(){if(relayThread)return true;relayStop=CreateEventW(0,TRUE,FALSE,0);relayWake=CreateEventW(0,FALSE,FALSE,0);if(relayStop&&relayWake)relayThread=CreateThread(0,0,relayMain,this,0,0);if(!relayThread){if(relayStop)CloseHandle(relayStop);if(relayWake)CloseHandle(relayWake);relayStop=relayWake=0;return false;}return true;}
void Device::attachRelay(Relay* r){if(!r)return;r->generation=generation;r->active=true;r->next=relays;relays=r;if(relayWake)SetEvent(relayWake);}
void Device::detachRelay(Relay* r){if(!r)return;r->active=false;Relay** q=&relays;while(*q&&*q!=r)q=&(*q)->next;if(*q)*q=r->next;r->next=0;if(relayWake)SetEvent(relayWake);}
DWORD WINAPI Device::relayMain(void* opaque){Device* d=(Device*)opaque;DWORD scan=0;for(;;){HANDLE handles[MAXIMUM_WAIT_OBJECTS];Relay* sets[MAXIMUM_WAIT_OBJECTS];DWORD indices[MAXIMUM_WAIT_OBJECTS];DWORD count=2,total=0;handles[0]=d->relayStop;handles[1]=d->relayWake;{Guard guard(d->lock);for(Relay* r=d->relays;r;r=r->next)if(r->active)total+=r->count;if(scan>=total)scan=0;DWORD at=0;for(Relay* r=d->relays;r&&count<MAXIMUM_WAIT_OBJECTS;r=r->next)if(r->active)for(DWORD i=0;i<r->count&&count<MAXIMUM_WAIT_OBJECTS;++i,++at)if(at>=scan){handles[count]=r->events[i];sets[count]=r;indices[count]=i;r->add();++count;}}
 DWORD wait=WaitForMultipleObjects(count,handles,FALSE,total>MAXIMUM_WAIT_OBJECTS-2?5:100);bool stop=wait==WAIT_OBJECT_0;
 if(wait>=WAIT_OBJECT_0+2&&wait<WAIT_OBJECT_0+count){DWORD at=wait-WAIT_OBJECT_0;Guard guard(d->lock);Relay* r=sets[at];if(!d->pending&&r->active&&r->generation==d->generation)SetEvent(r->targets[indices[at]]);}
 for(DWORD i=2;i<count;++i)sets[i]->release();if(stop)break;if(total>MAXIMUM_WAIT_OBJECTS-2)scan=(scan+MAXIMUM_WAIT_OBJECTS-2)%total;else scan=0;
 }return 0;}
Device::~Device(){if(monitor){monitor->shutdown();monitor->Release();monitor=0;}if(relayStop)SetEvent(relayStop);if(relayWake)SetEvent(relayWake);if(relayThread){WaitForSingleObject(relayThread,INFINITE);CloseHandle(relayThread);}if(relayStop)CloseHandle(relayStop);if(relayWake)CloseHandle(relayWake);drop(native);DeleteCriticalSection(&lock);}
void Buffer::cleanStage(){if(stage)stage->Stop();drop(sl);drop(st);drop(sn);drop(stage);releaseRelay(stageRelay);}
Buffer::~Buffer(){device->detachRelay(relay);cleanStage();if(group->proto==native)drop(group->proto);if(native)native->Stop();if(nn)nn->SetNotificationPositions(0,0);drop(nl);drop(nt);drop(nn);drop(native);releaseRelay(relay);releaseRetired(retired);dealloc(positions);}
HRESULT Buffer::interfaces(IDirectSoundBuffer* b,IDirectSound3DListener** l,IDirectSound3DBuffer** t,IDirectSoundNotify** n){HRESULT hr=S_OK;if(haveListener)hr=b->QueryInterface(gListener,(void**)l);if(SUCCEEDED(hr)&&haveThree)hr=b->QueryInterface(gThree,(void**)t);if(SUCCEEDED(hr)&&haveNotify)hr=b->QueryInterface(gNotify,(void**)n);return hr;}
HRESULT Buffer::seed(){if(!native)return S_OK;HRESULT hr=native->GetCaps(&caps);if(FAILED(hr))return hr;if(caps.dwFlags&DSBCAPS_CTRLVOLUME)native->GetVolume(&volume);if(caps.dwFlags&DSBCAPS_CTRLPAN)native->GetPan(&pan);if(caps.dwFlags&DSBCAPS_CTRLFREQUENCY)native->GetFrequency(&frequency);return S_OK;}
DWORD Buffer::current(ULONGLONG now,bool* live){DWORD size=group->desc.dwBufferBytes;bool active=wanted;ULONGLONG at=cursor;if(active&&size&&group->format){WAVEFORMATEX* f=(WAVEFORMATEX*)group->format;ULONGLONG rate=(ULONGLONG)(frequency?frequency:f->nSamplesPerSec)*f->nBlockAlign;at+=((now-cursorTime)*rate)/1000;if(playFlags&DSBPLAY_LOOPING)at%=size;else if(at>=size){at=size?size-1:0;active=false;}}if(live)*live=active;return (DWORD)at;}
ULONG Buffer::AddRef(){return (ULONG)InterlockedIncrement(&refs);}
ULONG Buffer::Release(){ULONG n=(ULONG)InterlockedDecrement(&refs);if(n)return n;Device* d=device;{Guard guard(d->lock);Buffer** p=&d->buffers;while(*p&&*p!=this)p=&(*p)->next;if(*p)*p=next;if(group->locked==this)group->locked=0;Group* g=group;delete this;if(!--g->refs){Group** q=&d->groups;while(*q&&*q!=g)q=&(*q)->next;if(*q)*q=g->next;delete g;}}d->Release();return 0;}
HRESULT Device::QueryInterface(REFIID id,void** p){if(!p)return E_POINTER;*p=0;if(eq(id,gUnknown)||eq(id,gDevice)){*p=(IDirectSound*)this;AddRef();return S_OK;}return E_NOINTERFACE;}
HRESULT Buffer::QueryInterface(REFIID id,void** p){if(!p)return E_POINTER;*p=0;Guard guard(device->lock);if(eq(id,gUnknown)||eq(id,gBuffer))*p=(IDirectSoundBuffer*)this;else if(eq(id,gListener)&&group->primary&&(group->desc.dwFlags&DSBCAPS_CTRL3D)){if(!haveListener){HRESULT hr=device->call([&](){return native->QueryInterface(gListener,(void**)&nl);});if(FAILED(hr)&&hr!=DSERR_BUFFERLOST)return hr;haveListener=true;if(nl){nl->GetAllParameters(&listener.state);listener.deferred=listener.state;listener.dirty=false;listener.dirtyMask=0;}}*p=(IDirectSound3DListener*)&listener;}else if(eq(id,gThree)&&!group->primary&&(group->desc.dwFlags&DSBCAPS_CTRL3D)){if(!haveThree){HRESULT hr=device->call([&](){return native->QueryInterface(gThree,(void**)&nt);});if(FAILED(hr)&&hr!=DSERR_BUFFERLOST)return hr;haveThree=true;if(nt){nt->GetAllParameters(&three.state);three.deferred=three.state;three.dirty=false;three.dirtyMask=0;}}*p=(IDirectSound3DBuffer*)&three;}else if(eq(id,gNotify)&&!group->primary&&(group->desc.dwFlags&DSBCAPS_CTRLPOSITIONNOTIFY)){if(!haveNotify){HRESULT hr=device->call([&](){return native->QueryInterface(gNotify,(void**)&nn);});if(FAILED(hr)&&hr!=DSERR_BUFFERLOST)return hr;haveNotify=true;}*p=(IDirectSoundNotify*)&notify;}else return E_NOINTERFACE;AddRef();return S_OK;}
#define EMBED_UNKNOWN(C) HRESULT C::QueryInterface(REFIID i,void**p){return owner->QueryInterface(i,p);}ULONG C::AddRef(){return owner->AddRef();}ULONG C::Release(){return owner->Release();}
EMBED_UNKNOWN(Listener) EMBED_UNKNOWN(Three) EMBED_UNKNOWN(Notify)

static HRESULT putPCM(IDirectSoundBuffer* b,Group* g,DWORD offset,DWORD count){if(!count)return S_OK;void *a=0,*c=0;DWORD na=0,nc=0;HRESULT hr=b->Lock(offset,count,&a,&na,&c,&nc,0);if(FAILED(hr))return hr;if(na+nc!=count||!a||(nc&&!c)){b->Unlock(a,na,c,nc);return E_FAIL;}DWORD first=g->desc.dwBufferBytes-offset;if(na>first){b->Unlock(a,na,c,nc);return E_FAIL;}memcpy(a,g->pcm+offset,na);if(nc)memcpy(c,g->pcm,nc);return b->Unlock(a,na,c,nc);}
bool Device::recover(){
 if(!pending||rebuilding)return !pending;for(Group* g=groups;g;g=g->next)if(g->locked){retryAt=GetTickCount64()+100;return false;}
 RouteSnapshot binding={};bool haveBinding=monitor&&monitor->read(&binding);if(monitor&&observedRouteEpoch&&!haveBinding){retryAt=GetTickCount64()+10;return false;}rebuilding=true;for(Buffer* b=buffers;b;b=b->next){b->stagePlayed=false;b->stageExpired=false;}++attempts;retryAt=GetTickCount64()+250;IDirectSound* fresh=0;GUID freshGuid={};HRESULT freshMapHr=mappedDefault(&freshGuid);if(haveBinding&&binding.injected){freshGuid=binding.mapped;freshMapHr=binding.mapHr;}ULONG freshEpoch=haveBinding?binding.epoch:observedRouteEpoch;DWORD freshState=haveBinding?binding.state:observedEndpointState;HRESULT hr=createNative(&fresh);GUID afterGuid={};HRESULT afterMapHr=mappedDefault(&afterGuid);RouteSnapshot afterBinding={};if(haveBinding&&binding.injected){afterGuid=freshGuid;afterMapHr=freshMapHr;if(monitor->read(&afterBinding)&&afterBinding.injected){afterGuid=afterBinding.mapped;afterMapHr=afterBinding.mapHr;}}if(SUCCEEDED(hr)&&(afterMapHr!=freshMapHr||!eq(afterGuid,freshGuid)))hr=DSERR_BUFFERLOST;int step=0;
 if(SUCCEEDED(hr)&&haveCoop)hr=fresh->SetCooperativeLevel(hwnd,coop);if(SUCCEEDED(hr)&&haveSpeakers)hr=fresh->SetSpeakerConfig(speakers);if(SUCCEEDED(hr)&&injected(step++))hr=last;
 // Primary/listener first, then PCM prototypes. All staging is private.
 for(int primaryPass=1;primaryPass>=0&&SUCCEEDED(hr);--primaryPass)for(Group* g=groups;g&&SUCCEEDED(hr);g=g->next){if((int)g->primary!=primaryPass)continue;DSBUFFERDESC desc=g->desc;desc.lpwfxFormat=g->primary?0:(WAVEFORMATEX*)g->format;hr=fresh->CreateSoundBuffer(&desc,&g->stage,0);if(SUCCEEDED(hr)){++groupCreates;if(g->primary&&g->formatSet)hr=g->stage->SetFormat((WAVEFORMATEX*)g->format);else if(!g->primary)hr=putPCM(g->stage,g,0,g->desc.dwBufferBytes);}if(SUCCEEDED(hr)&&injected(step++))hr=last;}
 ULONGLONG now=GetTickCount64();
 for(Buffer* b=buffers;b&&SUCCEEDED(hr);b=b->next){if(b->group->primary){b->stage=b->group->stage;b->stage->AddRef();}else hr=fresh->DuplicateSoundBuffer(b->group->stage,&b->stage);if(SUCCEEDED(hr))hr=b->interfaces(b->stage,&b->sl,&b->st,&b->sn);
  if(SUCCEEDED(hr)&&(b->caps.dwFlags&DSBCAPS_CTRLVOLUME))hr=b->stage->SetVolume(b->volume);if(SUCCEEDED(hr)&&(b->caps.dwFlags&DSBCAPS_CTRLPAN))hr=b->stage->SetPan(b->pan);if(SUCCEEDED(hr)&&(b->caps.dwFlags&DSBCAPS_CTRLFREQUENCY))hr=b->stage->SetFrequency(b->frequency);
  if(SUCCEEDED(hr)&&b->sl)hr=b->sl->SetAllParameters(&b->listener.state,DS3D_IMMEDIATE);if(SUCCEEDED(hr)&&b->sl&&b->listener.dirty)hr=b->sl->SetAllParameters(&b->listener.deferred,DS3D_DEFERRED);
  if(SUCCEEDED(hr)&&b->st)hr=b->st->SetAllParameters(&b->three.state,DS3D_IMMEDIATE);if(SUCCEEDED(hr)&&b->st&&b->three.dirty)hr=b->st->SetAllParameters(&b->three.deferred,DS3D_DEFERRED);
  if(SUCCEEDED(hr)&&b->sn&&b->positionCount){b->stageRelay=newRelay(b->positionCount,b->positions,b->relay);if(!b->stageRelay)hr=E_OUTOFMEMORY;else{hr=b->sn->SetNotificationPositions(b->positionCount,b->stageRelay->nativePositions);if(SUCCEEDED(hr)){b->stageRelay->bound=true;++notifyCalls;}}}
  if(SUCCEEDED(hr)&&!b->group->primary)hr=b->stage->SetCurrentPosition(b->current(now));if(SUCCEEDED(hr)&&injected(step++))hr=last;
 }
 // No staged buffer plays until every allocation/state/notification is ready.
 if(SUCCEEDED(hr))for(Buffer* b=buffers;b&&SUCCEEDED(hr);b=b->next){bool live=false;DWORD at=b->current(GetTickCount64(),&live);b->stageExpired=b->wanted&&!live;if(live){if(!b->group->primary)hr=b->stage->SetCurrentPosition(at);if(SUCCEEDED(hr)){++playCalls;hr=b->stage->Play(0,b->playPriority,b->playFlags);b->stagePlayed=SUCCEEDED(hr);}if(SUCCEEDED(hr)&&injected(step++))hr=last;}}
 if(SUCCEEDED(hr)){
  now=GetTickCount64();IDirectSound* old=native;native=fresh;fresh=0;++generation;for(Group* g=groups;g;g=g->next)drop(g->proto);
  for(Buffer* b=buffers;b;b=b->next){detachRelay(b->relay);if(b->native)b->native->Stop();if(b->nn)b->nn->SetNotificationPositions(0,0);drop(b->nl);drop(b->nt);drop(b->nn);drop(b->native);releaseRelay(b->relay);releaseRetired(b->retired);b->relay=b->stageRelay;b->stageRelay=0;attachRelay(b->relay);b->native=b->stage;b->stage=0;b->nl=b->sl;b->sl=0;b->nt=b->st;b->st=0;b->nn=b->sn;b->sn=0;bool live;b->cursor=b->current(now,&live);b->cursorTime=now;if(b->stageExpired&&!b->stagePlayed&&b->relay)for(DWORD i=0;i<b->relay->count;++i)if(b->relay->nativePositions[i].dwOffset==(DWORD)DSBPN_OFFSETSTOP||b->relay->nativePositions[i].dwOffset==b->group->desc.dwBufferBytes-1){bool already=false;for(DWORD j=0;j<i;++j)if(b->positions[j].hEventNotify==b->positions[i].hEventNotify&&(b->positions[j].dwOffset==(DWORD)DSBPN_OFFSETSTOP||b->positions[j].dwOffset==b->group->desc.dwBufferBytes-1))already=true;if(!already)SetEvent(b->relay->targets[i]);}b->wanted=live;}
  for(Group* g=groups;g;g=g->next){drop(g->proto);g->proto=g->stage;g->stage=0;}drop(old);acceptedMappedGuid=freshGuid;acceptedMapHr=freshMapHr;acceptedRouteEpoch=freshEpoch;acceptedEndpointState=freshState;pending=false;RouteSnapshot newest;if(monitor&&monitor->read(&newest)&&(newest.epoch!=freshEpoch||newest.mapHr!=freshMapHr||!eq(newest.mapped,freshGuid)))pending=true;++successes;last=S_OK;
 }else{++failures;last=hr;for(Buffer* b=buffers;b;b=b->next){if(b->stage)b->stage->Stop();b->cleanStage();}for(Group* g=groups;g;g=g->next)drop(g->stage);}
 drop(fresh);rebuilding=false;return !pending;
}
static HRESULT copyFormat(Group* g,LPCWAVEFORMATEX f){if(!f)return DSERR_INVALIDPARAM;DWORD n=sizeof(WAVEFORMATEX)+f->cbSize;if(n>65536||!f->nBlockAlign||!f->nSamplesPerSec)return DSERR_BADFORMAT;BYTE* p=(BYTE*)alloc(n);if(!p)return E_OUTOFMEMORY;memcpy(p,f,n);dealloc(g->format);g->format=p;g->formatBytes=n;return S_OK;}
HRESULT Device::CreateSoundBuffer(LPCDSBUFFERDESC desc,LPDIRECTSOUNDBUFFER* out,LPUNKNOWN outer){if(!out)return DSERR_INVALIDPARAM;*out=0;if(outer)return DSERR_NOAGGREGATION;if(!desc||desc->dwSize!=sizeof(DSBUFFERDESC))return DSERR_INVALIDPARAM;Guard guard(lock);bool primary=(desc->dwFlags&DSBCAPS_PRIMARYBUFFER)!=0;if(primary)for(Buffer* b=buffers;b;b=b->next)if(b->group->primary){b->AddRef();*out=b;return S_OK;}
 unsigned groupCount=0;SIZE_T pcmTotal=0;for(Group* q=groups;q;q=q->next){++groupCount;if(!q->primary)pcmTotal+=q->desc.dwBufferBytes;}if(groupCount>=4096||(!primary&&(desc->dwBufferBytes>0x10000000u||pcmTotal>0x10000000u-desc->dwBufferBytes)))return E_OUTOFMEMORY;Group* g=new(std::nothrow) Group;if(!g)return E_OUTOFMEMORY;g->device=this;g->desc=*desc;g->desc.lpwfxFormat=0;g->primary=primary;HRESULT hr=S_OK;if(!primary){if(!desc->dwBufferBytes||desc->dwBufferBytes>0x10000000u)hr=DSERR_INVALIDPARAM;else hr=copyFormat(g,desc->lpwfxFormat);if(SUCCEEDED(hr)){g->pcm=(BYTE*)alloc(desc->dwBufferBytes);if(!g->pcm)hr=E_OUTOFMEMORY;else if(((WAVEFORMATEX*)g->format)->wBitsPerSample==8)memset(g->pcm,128,desc->dwBufferBytes);}}
 Buffer* b=SUCCEEDED(hr)?new(std::nothrow) Buffer(this,g):0;if(SUCCEEDED(hr)&&!b)hr=E_OUTOFMEMORY;
 if(SUCCEEDED(hr)){hr=call([&](){return native->CreateSoundBuffer(desc,&b->native,0);});if(hr==DSERR_BUFFERLOST)hr=S_OK;if(SUCCEEDED(hr)&&b->native){g->proto=b->native;g->proto->AddRef();hr=b->seed();if(hr==DSERR_BUFFERLOST){mark();hr=S_OK;}}}
 if(FAILED(hr)){delete b;delete g;return hr;}g->refs=1;g->next=groups;groups=g;b->next=buffers;buffers=b;AddRef();*out=b;return S_OK;
}
HRESULT Device::DuplicateSoundBuffer(LPDIRECTSOUNDBUFFER source,LPDIRECTSOUNDBUFFER* out){if(!out)return DSERR_INVALIDPARAM;*out=0;Guard guard(lock);Buffer* src=0;for(Buffer* b=buffers;b;b=b->next)if((IDirectSoundBuffer*)b==source){src=b;break;}if(!src||src->group->primary)return DSERR_INVALIDPARAM;Buffer* b=new(std::nothrow) Buffer(this,src->group);if(!b)return E_OUTOFMEMORY;HRESULT hr=call([&](){return native->DuplicateSoundBuffer(src->native,&b->native);});if(hr==DSERR_BUFFERLOST)hr=S_OK;if(FAILED(hr)){delete b;return hr;}b->caps=src->caps;b->volume=src->volume;b->pan=src->pan;b->frequency=src->frequency;b->three.state=src->three.state;b->three.deferred=src->three.deferred;b->three.dirty=src->three.dirty;b->three.dirtyMask=src->three.dirtyMask;if(src->haveThree){b->haveThree=true;if(b->native){hr=b->native->QueryInterface(gThree,(void**)&b->nt);if(SUCCEEDED(hr))hr=b->nt->SetAllParameters(&b->three.state,DS3D_IMMEDIATE);if(SUCCEEDED(hr)&&b->three.dirty)hr=b->nt->SetAllParameters(&b->three.deferred,DS3D_DEFERRED);if(hr==DSERR_BUFFERLOST){mark();hr=S_OK;}if(FAILED(hr)){delete b;return hr;}}}src->group->refs++;b->next=buffers;buffers=b;AddRef();*out=b;return S_OK;}
HRESULT Device::GetCaps(LPDSCAPS p){if(!p||p->dwSize!=sizeof(*p))return DSERR_INVALIDPARAM;Guard guard(lock);before();if(pending){*p=caps;return S_OK;}HRESULT hr=call([&](){return native->GetCaps(p);});if(hr==DSERR_BUFFERLOST){*p=caps;return S_OK;}if(SUCCEEDED(hr))caps=*p;return hr;}
HRESULT Device::SetCooperativeLevel(HWND w,DWORD c){if(!w||c<DSSCL_NORMAL||c>DSSCL_WRITEPRIMARY)return DSERR_INVALIDPARAM;Guard guard(lock);HWND old=hwnd;DWORD oc=coop;bool had=haveCoop;hwnd=w;coop=c;haveCoop=true;HRESULT hr=call([&](){return native->SetCooperativeLevel(w,c);});if(FAILED(hr)&&hr!=DSERR_BUFFERLOST){hwnd=old;coop=oc;haveCoop=had;}return mask(hr);}
HRESULT Device::Compact(){Guard guard(lock);return mask(call([&](){return native->Compact();}));}
HRESULT Device::GetSpeakerConfig(LPDWORD p){if(!p)return DSERR_INVALIDPARAM;Guard guard(lock);HRESULT hr=call([&](){return native->GetSpeakerConfig(p);});if(hr==DSERR_BUFFERLOST){*p=speakers;return S_OK;}if(SUCCEEDED(hr)){speakers=*p;haveSpeakers=true;}return hr;}
HRESULT Device::SetSpeakerConfig(DWORD s){Guard guard(lock);DWORD old=speakers;bool had=haveSpeakers;speakers=s;haveSpeakers=true;HRESULT hr=call([&](){return native->SetSpeakerConfig(s);});if(FAILED(hr)&&hr!=DSERR_BUFFERLOST){speakers=old;haveSpeakers=had;}return mask(hr);}
HRESULT Buffer::GetCaps(LPDSBCAPS p){if(!p||p->dwSize!=sizeof(*p))return DSERR_INVALIDPARAM;Guard guard(device->lock);device->before();*p=caps;return S_OK;}
HRESULT Buffer::GetCurrentPosition(LPDWORD p,LPDWORD w){if(!p&&!w)return DSERR_INVALIDPARAM;Guard guard(device->lock);HRESULT hr=device->call([&](){return native->GetCurrentPosition(p,w);});if(hr==DSERR_BUFFERLOST){DWORD at=current(GetTickCount64());if(p)*p=at;if(w)*w=at;return S_OK;}if(SUCCEEDED(hr)&&p){cursor=*p;cursorTime=GetTickCount64();}return hr;}
HRESULT Buffer::GetFormat(LPWAVEFORMATEX p,DWORD n,LPDWORD written){Guard guard(device->lock);device->before();if(group->primary&&!group->format){DWORD bytes=0;HRESULT hr=device->call([&](){return native->GetFormat(0,0,&bytes);});if(FAILED(hr))return hr;BYTE* f=(BYTE*)alloc(bytes);if(!f)return E_OUTOFMEMORY;hr=native->GetFormat((WAVEFORMATEX*)f,bytes,&bytes);if(FAILED(hr)){dealloc(f);return hr;}group->format=f;group->formatBytes=bytes;}
 if(written)*written=group->formatBytes;if(!p)return written?S_OK:DSERR_INVALIDPARAM;if(n<group->formatBytes)return DSERR_INVALIDPARAM;memcpy(p,group->format,group->formatBytes);return S_OK;}
#define SIMPLE_GET(name,type,field,cap) HRESULT Buffer::name(type* p){if(!p)return DSERR_INVALIDPARAM;Guard guard(device->lock);device->before();if(!(caps.dwFlags&cap))return DSERR_CONTROLUNAVAIL;*p=field;return S_OK;}
SIMPLE_GET(GetVolume,LONG,volume,DSBCAPS_CTRLVOLUME) SIMPLE_GET(GetPan,LONG,pan,DSBCAPS_CTRLPAN) SIMPLE_GET(GetFrequency,DWORD,frequency,DSBCAPS_CTRLFREQUENCY)
HRESULT Buffer::GetStatus(LPDWORD p){if(!p)return DSERR_INVALIDPARAM;Guard guard(device->lock);HRESULT hr=device->call([&](){HRESULT h=native->GetStatus(p);if(SUCCEEDED(h)&&(*p&DSBSTATUS_BUFFERLOST))return (HRESULT)DSERR_BUFFERLOST;return h;});if(hr==DSERR_BUFFERLOST){bool live;current(GetTickCount64(),&live);*p=live?DSBSTATUS_PLAYING|((playFlags&DSBPLAY_LOOPING)?DSBSTATUS_LOOPING:0):0;return S_OK;}if(SUCCEEDED(hr)&&!(*p&DSBSTATUS_PLAYING)&&!(playFlags&DSBPLAY_LOOPING))wanted=false;return hr;}
HRESULT Buffer::Initialize(LPDIRECTSOUND,LPCDSBUFFERDESC){return DSERR_ALREADYINITIALIZED;}
HRESULT Buffer::Lock(DWORD offset,DWORD bytes,LPVOID* a,LPDWORD na,LPVOID* b,LPDWORD nb,DWORD flags){if(!a||!na||!b||!nb)return DSERR_INVALIDPARAM;*a=*b=0;*na=*nb=0;Guard guard(device->lock);if(group->primary)return DSERR_PRIOLEVELNEEDED;if(group->locked)return DSERR_INVALIDCALL;if(flags&~(DSBLOCK_FROMWRITECURSOR|DSBLOCK_ENTIREBUFFER))return DSERR_INVALIDPARAM;device->before();DWORD size=group->desc.dwBufferBytes;if(flags&DSBLOCK_ENTIREBUFFER){offset=0;bytes=size;}else if(flags&DSBLOCK_FROMWRITECURSOR){DWORD wr=0;HRESULT hr=GetCurrentPosition(0,&wr);if(FAILED(hr))return hr;offset=(DWORD)(((ULONGLONG)wr+offset)%size);}if(offset>=size||bytes>size||!bytes)return DSERR_INVALIDPARAM;group->locked=this;lockOffset=offset;lockBytes=bytes;lockFirst=(bytes<size-offset)?bytes:size-offset;lockA=group->pcm+offset;lockB=bytes>lockFirst?group->pcm:0;*a=lockA;*na=lockFirst;*b=lockB;*nb=bytes-lockFirst;return S_OK;}
HRESULT Buffer::Unlock(LPVOID a,DWORD na,LPVOID b,DWORD nb){Guard guard(device->lock);if(group->locked!=this||a!=lockA||b!=lockB||na!=lockFirst||nb!=lockBytes-lockFirst)return DSERR_INVALIDPARAM;DWORD offset=lockOffset,count=lockBytes;group->locked=0;lockA=lockB=0;lockBytes=0;if(device->pending)device->retryAt=0;HRESULT hr=device->call([&](){return putPCM(native,group,offset,count);});return device->mask(hr);}
HRESULT Buffer::Play(DWORD a,DWORD b,DWORD flags){if(a||(flags&~0x3fu)||((flags&6)==6))return DSERR_INVALIDPARAM;Guard guard(device->lock);if(b&&!(caps.dwFlags&DSBCAPS_LOCDEFER))return DSERR_INVALIDPARAM;if(group->locked)return DSERR_INVALIDCALL;bool old=wanted;DWORD oldFlags=playFlags,oldPriority=playPriority;cursor=current(GetTickCount64());cursorTime=GetTickCount64();wanted=true;playFlags=flags;playPriority=b;HRESULT hr=device->call([&](){++device->playCalls;return native->Play(a,b,flags);});if(FAILED(hr)&&hr!=DSERR_BUFFERLOST){wanted=old;playFlags=oldFlags;playPriority=oldPriority;}return device->mask(hr);}
HRESULT Buffer::Stop(){Guard guard(device->lock);cursor=current(GetTickCount64());cursorTime=GetTickCount64();wanted=false;return device->mask(device->call([&](){return native->Stop();}));}
HRESULT Buffer::SetCurrentPosition(DWORD value){Guard guard(device->lock);if(group->primary||value>=group->desc.dwBufferBytes)return DSERR_INVALIDPARAM;DWORD old=cursor;ULONGLONG oldTime=cursorTime;cursor=value;cursorTime=GetTickCount64();HRESULT hr=device->call([&](){return native->SetCurrentPosition(value);});if(FAILED(hr)&&hr!=DSERR_BUFFERLOST){cursor=old;cursorTime=oldTime;}return device->mask(hr);}
HRESULT Buffer::SetFormat(LPCWAVEFORMATEX f){Guard guard(device->lock);if(!group->primary)return DSERR_INVALIDCALL;Group temp;HRESULT hr=copyFormat(&temp,f);if(FAILED(hr))return hr;hr=device->call([&](){return native->SetFormat(f);});if(SUCCEEDED(hr)||hr==DSERR_BUFFERLOST){dealloc(group->format);group->format=temp.format;temp.format=0;group->formatBytes=temp.formatBytes;group->formatSet=true;}return device->mask(hr);}
#define SIMPLE_SET(name,type,field,cap,valid) HRESULT Buffer::name(type v){if(!(valid))return DSERR_INVALIDPARAM;Guard guard(device->lock);if(!(caps.dwFlags&cap))return DSERR_CONTROLUNAVAIL;type old=field;field=v;HRESULT hr=device->call([&](){return native->name(v);});if(FAILED(hr)&&hr!=DSERR_BUFFERLOST)field=old;return device->mask(hr);}
SIMPLE_SET(SetVolume,LONG,volume,DSBCAPS_CTRLVOLUME,v>=DSBVOLUME_MIN&&v<=DSBVOLUME_MAX)
SIMPLE_SET(SetPan,LONG,pan,DSBCAPS_CTRLPAN,v>=DSBPAN_LEFT&&v<=DSBPAN_RIGHT)
HRESULT Buffer::SetFrequency(DWORD v){if(v!=0&&(v<DSBFREQUENCY_MIN||v>DSBFREQUENCY_MAX))return DSERR_INVALIDPARAM;Guard guard(device->lock);if(!(caps.dwFlags&DSBCAPS_CTRLFREQUENCY))return DSERR_CONTROLUNAVAIL;DWORD old=frequency;ULONGLONG now=GetTickCount64();cursor=current(now);cursorTime=now;frequency=v?v:(group->format?((WAVEFORMATEX*)group->format)->nSamplesPerSec:0);HRESULT hr=device->call([&](){return native->SetFrequency(v);});if(FAILED(hr)&&hr!=DSERR_BUFFERLOST)frequency=old;return device->mask(hr);}
HRESULT Buffer::Restore(){Guard guard(device->lock);if(group->locked)return DSERR_INVALIDCALL;device->before();if(device->pending)return S_OK;HRESULT hr=native->Restore();if(SUCCEEDED(hr)&&!group->primary)hr=putPCM(native,group,0,group->desc.dwBufferBytes);if(hr==DSERR_BUFFERLOST){device->mark();device->before();return S_OK;}return hr;}
HRESULT Notify::SetNotificationPositions(DWORD n,LPCDSBPOSITIONNOTIFY p){if(n&&!p)return DSERR_INVALIDPARAM;if(n>4096)return DSERR_INVALIDPARAM;Device* d=owner->device;Guard guard(d->lock);DWORD total=n;for(Buffer* b=d->buffers;b;b=b->next)if(b!=owner)total+=b->positionCount;if(total>4096)return E_OUTOFMEMORY;for(DWORD i=0;i<n;++i)if(!p[i].hEventNotify||(p[i].dwOffset!=(DWORD)DSBPN_OFFSETSTOP&&p[i].dwOffset>=owner->group->desc.dwBufferBytes))return DSERR_INVALIDPARAM;if(n&&!d->startRelay())return E_OUTOFMEMORY;DSBPOSITIONNOTIFY* copy=n?(DSBPOSITIONNOTIFY*)alloc(n*sizeof(*p)):0;if(n&&!copy)return E_OUTOFMEMORY;if(n)memcpy(copy,p,n*sizeof(*p));Relay* fresh=newRelay(n,p);if(n&&!fresh){dealloc(copy);return E_OUTOFMEMORY;}HRESULT hr=d->call([&](){if(fresh)fresh->bound=true;HRESULT h=owner->nn->SetNotificationPositions(n,fresh?fresh->nativePositions:0);if(SUCCEEDED(h))++d->notifyCalls;return h;});if(SUCCEEDED(hr)||hr==DSERR_BUFFERLOST){d->detachRelay(owner->relay);if(hr==DSERR_BUFFERLOST&&owner->relay&&owner->relay->bound){owner->relay->retiredNext=owner->retired;owner->retired=owner->relay;owner->relay=0;}else releaseRelay(owner->relay);dealloc(owner->positions);owner->positions=copy;owner->positionCount=n;copy=0;owner->relay=fresh;fresh=0;if(!d->pending)d->attachRelay(owner->relay);}dealloc(copy);releaseRelay(fresh);return d->mask(hr);}

// Stable cached 3D interfaces; mutation is validated by the native all-parameter
// call. Deferred state is replayed as deferred, and committed only on Commit.
#define LGET(name,type,field) HRESULT Listener::name(type* p){if(!p)return DSERR_INVALIDPARAM;Guard guard(owner->device->lock);owner->device->before();*p=state.field;return S_OK;}
#define TGET(name,type,field) HRESULT Three::name(type* p){if(!p)return DSERR_INVALIDPARAM;Guard guard(owner->device->lock);owner->device->before();*p=state.field;return S_OK;}
LGET(GetDistanceFactor,D3DVALUE,flDistanceFactor) LGET(GetDopplerFactor,D3DVALUE,flDopplerFactor) LGET(GetRolloffFactor,D3DVALUE,flRolloffFactor) LGET(GetPosition,D3DVECTOR,vPosition) LGET(GetVelocity,D3DVECTOR,vVelocity)
TGET(GetConeOrientation,D3DVECTOR,vConeOrientation) TGET(GetConeOutsideVolume,LONG,lConeOutsideVolume) TGET(GetMaxDistance,D3DVALUE,flMaxDistance) TGET(GetMinDistance,D3DVALUE,flMinDistance) TGET(GetMode,DWORD,dwMode) TGET(GetPosition,D3DVECTOR,vPosition) TGET(GetVelocity,D3DVECTOR,vVelocity)
HRESULT Listener::GetAllParameters(LPDS3DLISTENER p){if(!p||p->dwSize!=sizeof(*p))return DSERR_INVALIDPARAM;Guard guard(owner->device->lock);owner->device->before();*p=state;return S_OK;}
HRESULT Three::GetAllParameters(LPDS3DBUFFER p){if(!p||p->dwSize!=sizeof(*p))return DSERR_INVALIDPARAM;Guard guard(owner->device->lock);owner->device->before();*p=state;return S_OK;}
HRESULT Listener::GetOrientation(LPD3DVECTOR a,LPD3DVECTOR b){if(!a||!b)return DSERR_INVALIDPARAM;Guard guard(owner->device->lock);owner->device->before();*a=state.vOrientFront;*b=state.vOrientTop;return S_OK;}
HRESULT Three::GetConeAngles(LPDWORD a,LPDWORD b){if(!a||!b)return DSERR_INVALIDPARAM;Guard guard(owner->device->lock);owner->device->before();*a=state.dwInsideConeAngle;*b=state.dwOutsideConeAngle;return S_OK;}
static bool finite3(float v){union{float f;DWORD u;} x;x.f=v;return (x.u&0x7f800000u)!=0x7f800000u;}
static bool vecok(const D3DVECTOR& v){return finite3(v.x)&&finite3(v.y)&&finite3(v.z);}
static bool listenerValid(LPCDS3DLISTENER p){if(!p||p->dwSize!=sizeof(*p)||!vecok(p->vPosition)||!vecok(p->vVelocity)||!vecok(p->vOrientFront)||!vecok(p->vOrientTop)||!finite3(p->flDistanceFactor)||p->flDistanceFactor<=0||!finite3(p->flRolloffFactor)||p->flRolloffFactor<0||p->flRolloffFactor>10||!finite3(p->flDopplerFactor)||p->flDopplerFactor<0||p->flDopplerFactor>10)return false;double x=(double)p->vOrientFront.y*p->vOrientTop.z-(double)p->vOrientFront.z*p->vOrientTop.y,y=(double)p->vOrientFront.z*p->vOrientTop.x-(double)p->vOrientFront.x*p->vOrientTop.z,z=(double)p->vOrientFront.x*p->vOrientTop.y-(double)p->vOrientFront.y*p->vOrientTop.x;return x*x+y*y+z*z>0;}
static bool threeValid(LPCDS3DBUFFER p){return p&&p->dwSize==sizeof(*p)&&vecok(p->vPosition)&&vecok(p->vVelocity)&&vecok(p->vConeOrientation)&&p->dwInsideConeAngle<=360&&p->dwOutsideConeAngle<=360&&p->lConeOutsideVolume>=-10000&&p->lConeOutsideVolume<=0&&finite3(p->flMinDistance)&&p->flMinDistance>0&&finite3(p->flMaxDistance)&&p->flMaxDistance>0&&p->dwMode<=DS3DMODE_DISABLE;}
static void mergeL(DS3DLISTENER& a,const DS3DLISTENER& b,DWORD mask){if(mask&1)a.vPosition=b.vPosition;if(mask&2)a.vVelocity=b.vVelocity;if(mask&4){a.vOrientFront=b.vOrientFront;a.vOrientTop=b.vOrientTop;}if(mask&8)a.flDistanceFactor=b.flDistanceFactor;if(mask&16)a.flRolloffFactor=b.flRolloffFactor;if(mask&32)a.flDopplerFactor=b.flDopplerFactor;}
static void mergeT(DS3DBUFFER& a,const DS3DBUFFER& b,DWORD mask){if(mask&1)a.vPosition=b.vPosition;if(mask&2)a.vVelocity=b.vVelocity;if(mask&4){a.dwInsideConeAngle=b.dwInsideConeAngle;a.dwOutsideConeAngle=b.dwOutsideConeAngle;}if(mask&8)a.vConeOrientation=b.vConeOrientation;if(mask&16)a.lConeOutsideVolume=b.lConeOutsideVolume;if(mask&32)a.flMinDistance=b.flMinDistance;if(mask&64)a.flMaxDistance=b.flMaxDistance;if(mask&128)a.dwMode=b.dwMode;}
HRESULT Listener::SetAllParameters(LPCDS3DLISTENER p,DWORD a){return apply(p,a,63);}
HRESULT Three::SetAllParameters(LPCDS3DBUFFER p,DWORD a){return apply(p,a,255);}
HRESULT Listener::apply(LPCDS3DLISTENER p,DWORD a,DWORD mask){if(!listenerValid(p)||a>DS3D_DEFERRED)return DSERR_INVALIDPARAM;Device* d=owner->device;Guard guard(d->lock);DS3DLISTENER old=state,od=deferred;DWORD om=dirtyMask;if(a==DS3D_DEFERRED){mergeL(deferred,*p,mask);dirtyMask|=mask;}else{mergeL(state,*p,mask);mergeL(deferred,*p,mask);dirtyMask&=~mask;}dirty=dirtyMask!=0;HRESULT hr=d->call([&](){HRESULT h=owner->nl->SetAllParameters(a==DS3D_DEFERRED?&deferred:&state,a);if(SUCCEEDED(h)&&a==DS3D_IMMEDIATE&&dirty)h=owner->nl->SetAllParameters(&deferred,DS3D_DEFERRED);return h;});if(FAILED(hr)&&hr!=DSERR_BUFFERLOST){state=old;deferred=od;dirtyMask=om;dirty=om!=0;}return d->mask(hr);}
HRESULT Three::apply(LPCDS3DBUFFER p,DWORD a,DWORD mask){if(!threeValid(p)||a>DS3D_DEFERRED)return DSERR_INVALIDPARAM;Device* d=owner->device;Guard guard(d->lock);DS3DBUFFER old=state,od=deferred;DWORD om=dirtyMask;if(a==DS3D_DEFERRED){mergeT(deferred,*p,mask);dirtyMask|=mask;}else{mergeT(state,*p,mask);mergeT(deferred,*p,mask);dirtyMask&=~mask;}dirty=dirtyMask!=0;HRESULT hr=d->call([&](){HRESULT h=owner->nt->SetAllParameters(a==DS3D_DEFERRED?&deferred:&state,a);if(SUCCEEDED(h)&&a==DS3D_IMMEDIATE&&dirty)h=owner->nt->SetAllParameters(&deferred,DS3D_DEFERRED);return h;});if(FAILED(hr)&&hr!=DSERR_BUFFERLOST){state=old;deferred=od;dirtyMask=om;dirty=om!=0;}return d->mask(hr);}
#define LSET(name,field,mask) HRESULT Listener::name(D3DVALUE v,DWORD a){Guard g(owner->device->lock);DS3DLISTENER p=(a==DS3D_DEFERRED&&dirty)?deferred:state;p.field=v;return apply(&p,a,mask);}
#define TSET(name,type,field,mask) HRESULT Three::name(type v,DWORD a){Guard g(owner->device->lock);DS3DBUFFER p=(a==DS3D_DEFERRED&&dirty)?deferred:state;p.field=v;return apply(&p,a,mask);}
LSET(SetDistanceFactor,flDistanceFactor,8) LSET(SetDopplerFactor,flDopplerFactor,32) LSET(SetRolloffFactor,flRolloffFactor,16)
TSET(SetConeOutsideVolume,LONG,lConeOutsideVolume,16) TSET(SetMaxDistance,D3DVALUE,flMaxDistance,64) TSET(SetMinDistance,D3DVALUE,flMinDistance,32) TSET(SetMode,DWORD,dwMode,128)
#define LVEC(name,field,mask) HRESULT Listener::name(D3DVALUE x,D3DVALUE y,D3DVALUE z,DWORD a){Guard g(owner->device->lock);DS3DLISTENER p=(a==DS3D_DEFERRED&&dirty)?deferred:state;p.field.x=x;p.field.y=y;p.field.z=z;return apply(&p,a,mask);}
#define TVEC(name,field,mask) HRESULT Three::name(D3DVALUE x,D3DVALUE y,D3DVALUE z,DWORD a){Guard g(owner->device->lock);DS3DBUFFER p=(a==DS3D_DEFERRED&&dirty)?deferred:state;p.field.x=x;p.field.y=y;p.field.z=z;return apply(&p,a,mask);}
LVEC(SetPosition,vPosition,1) LVEC(SetVelocity,vVelocity,2) TVEC(SetPosition,vPosition,1) TVEC(SetVelocity,vVelocity,2) TVEC(SetConeOrientation,vConeOrientation,8)
HRESULT Listener::SetOrientation(D3DVALUE x,D3DVALUE y,D3DVALUE z,D3DVALUE tx,D3DVALUE ty,D3DVALUE tz,DWORD a){Guard g(owner->device->lock);DS3DLISTENER p=(a==DS3D_DEFERRED&&dirty)?deferred:state;p.vOrientFront.x=x;p.vOrientFront.y=y;p.vOrientFront.z=z;p.vOrientTop.x=tx;p.vOrientTop.y=ty;p.vOrientTop.z=tz;return apply(&p,a,4);}
HRESULT Three::SetConeAngles(DWORD i,DWORD o,DWORD a){Guard g(owner->device->lock);DS3DBUFFER p=(a==DS3D_DEFERRED&&dirty)?deferred:state;p.dwInsideConeAngle=i;p.dwOutsideConeAngle=o;return apply(&p,a,4);}
HRESULT Listener::CommitDeferredSettings(){Device* d=owner->device;Guard guard(d->lock);HRESULT hr=d->call([&](){return owner->nl->CommitDeferredSettings();});if(SUCCEEDED(hr)||hr==DSERR_BUFFERLOST){for(Buffer* b=d->buffers;b;b=b->next){if(b->listener.dirty){b->listener.state=b->listener.deferred;b->listener.dirty=false;b->listener.dirtyMask=0;}if(b->three.dirty){b->three.state=b->three.deferred;b->three.dirty=false;b->three.dirtyMask=0;}}}return d->mask(hr);}

extern "C" __declspec(dllexport) HRESULT __cdecl REA_DirectSoundCreate(LPCGUID guid,IDirectSound** out,IUnknown* outer){if(!out)return DSERR_INVALIDPARAM;*out=0;if(outer)return DSERR_NOAGGREGATION;GUID zero={};if(guid&&!eq(*guid,zero)&&!eq(*guid,gDefault))return DSERR_UNSUPPORTED;Monitor* observation=new(std::nothrow) Monitor;if(observation)observation->start();GUID initialGuid={};HRESULT initialHr=mappedDefault(&initialGuid);RouteSnapshot initial={};bool observed=observation&&observation->read(&initial);IDirectSound* native=0;HRESULT hr=createNative(&native);if(FAILED(hr)){if(observation){observation->shutdown();observation->Release();}return hr;}GUID after={};HRESULT afterHr=mappedDefault(&after);Device* d=new(std::nothrow) Device(native,observation,initialGuid,initialHr,observed?initial.epoch:0,observed?initial.state:0);if(!d){drop(native);if(observation){observation->shutdown();observation->Release();}return E_OUTOFMEMORY;}if(afterHr!=initialHr||!eq(initialGuid,after))d->pending=true;*out=d;return hr;}
#ifdef REA_AUDIO_TEST
extern "C" __declspec(dllexport) HRESULT __cdecl REA_TestDeviceForceLoss(void* proxy){if(!proxy)return E_POINTER;Device* d=(Device*)proxy;Guard guard(d->lock);d->pending=true;d->retryAt=0;return S_OK;}
extern "C" __declspec(dllexport) HRESULT __cdecl REA_TestDeviceFailNextRebuild(void* proxy,LONG afterStep,HRESULT failure){if(!proxy||SUCCEEDED(failure))return E_INVALIDARG;Device* d=(Device*)proxy;Guard guard(d->lock);d->failStep=afterStep;d->failHr=failure;return S_OK;}
extern "C" __declspec(dllexport) ULONG __cdecl REA_TestDeviceStatus(void* proxy,unsigned index){if(!proxy)return 0;Device* d=(Device*)proxy;Guard guard(d->lock);ULONG n=0;switch(index){case 0:return d->generation;case 1:return d->attempts;case 2:return d->successes;case 3:return d->failures;case 4:return d->pending;case 5:for(Buffer* b=d->buffers;b;b=b->next)++n;break;case 6:for(Group* g=d->groups;g;g=g->next)++n;break;case 7:for(Group* g=d->groups;g;g=g->next)if(!g->primary)n+=g->desc.dwBufferBytes;break;case 8:return (ULONG)d->last;case 9:for(Group* g=d->groups;g;g=g->next)if(g->locked)++n;break;case 10:return d->playCalls;case 11:return d->notifyCalls;case 12:return d->groupCreates;}return n;}
extern "C" __declspec(dllexport) HRESULT __cdecl REA_TestProxyReadNativePCM(void* proxy,ULONG offset,void* output,ULONG bytes){if(!proxy||(!output&&bytes))return E_POINTER;Buffer* b=(Buffer*)proxy;Guard guard(b->device->lock);if(b->group->primary||offset>=b->group->desc.dwBufferBytes||bytes>b->group->desc.dwBufferBytes||!bytes)return E_INVALIDARG;if(b->device->pending||!b->native)return DSERR_BUFFERLOST;void *a=0,*c=0;DWORD na=0,nc=0;HRESULT hr=b->native->Lock(offset,bytes,&a,&na,&c,&nc,0);if(FAILED(hr))return hr;if(na+nc!=bytes||!a||(nc&&!c)){b->native->Unlock(a,na,c,nc);return E_FAIL;}memcpy(output,a,na);if(nc)memcpy((BYTE*)output+na,c,nc);return b->native->Unlock(a,na,c,nc);}
extern "C" __declspec(dllexport) HRESULT __cdecl REA_TestProxyNativeStatus(void* proxy,ULONG* out){if(!proxy||!out)return E_POINTER;Buffer* b=(Buffer*)proxy;Guard guard(b->device->lock);return b->native?b->native->GetStatus(out):DSERR_BUFFERLOST;}
extern "C" __declspec(dllexport) HRESULT __cdecl REA_TestProxyNativeCursor(void* proxy,ULONG* p,ULONG* w){if(!proxy||(!p&&!w))return E_POINTER;Buffer* b=(Buffer*)proxy;Guard guard(b->device->lock);return b->native?b->native->GetCurrentPosition(p,w):DSERR_BUFFERLOST;}
#define TEST_NATIVE_VALUE(exportName,type,method) extern "C" __declspec(dllexport) HRESULT __cdecl exportName(void* proxy,type* p){if(!proxy||!p)return E_POINTER;Buffer* b=(Buffer*)proxy;Guard guard(b->device->lock);return b->native?b->native->method(p):DSERR_BUFFERLOST;}
TEST_NATIVE_VALUE(REA_TestProxyNativeVolume,LONG,GetVolume) TEST_NATIVE_VALUE(REA_TestProxyNativePan,LONG,GetPan) TEST_NATIVE_VALUE(REA_TestProxyNativeFrequency,ULONG,GetFrequency)
extern "C" __declspec(dllexport) HRESULT __cdecl REA_TestProxyNative3DParameters(void* proxy,void* p,ULONG isListener){if(!proxy||!p)return E_POINTER;if(isListener){Listener* l=(Listener*)proxy;Guard guard(l->owner->device->lock);return l->owner->nl?l->owner->nl->GetAllParameters((DS3DLISTENER*)p):DSERR_BUFFERLOST;}Three* t=(Three*)proxy;Guard guard(t->owner->device->lock);return t->owner->nt?t->owner->nt->GetAllParameters((DS3DBUFFER*)p):DSERR_BUFFERLOST;}
extern "C" __declspec(dllexport) HRESULT __cdecl REA_TestDeviceSetRoute(void* proxy,const GUID* mapped,DWORD state){if(!proxy)return E_POINTER;Device* d=(Device*)proxy;Guard guard(d->lock);if(!d->monitor)return E_PENDING;return d->monitor->setRoute(mapped,state);}
extern "C" __declspec(dllexport) HRESULT __cdecl REA_TestDeviceRouteEvent(void* proxy,unsigned kind){if(!proxy)return E_POINTER;Device* d=(Device*)proxy;Guard guard(d->lock);return d->monitor?d->monitor->testEvent(kind):E_PENDING;}
extern "C" __declspec(dllexport) HRESULT __cdecl REA_TestDeviceRouteGUIDs(void* proxy,GUID* accepted,GUID* observed){if(!proxy||!accepted||!observed)return E_POINTER;Device* d=(Device*)proxy;Guard guard(d->lock);*accepted=d->acceptedMappedGuid;RouteSnapshot s;if(!d->monitor||!d->monitor->read(&s)){memset(observed,0,sizeof(*observed));return E_PENDING;}*observed=s.mapped;return S_OK;}
extern "C" __declspec(dllexport) ULONG __cdecl REA_TestDeviceRouteStatus(void* proxy,unsigned index){if(!proxy)return 0;Device* d=(Device*)proxy;Guard guard(d->lock);Monitor* m=d->monitor;if(!m)return 0;RouteSnapshot s={};bool ready=m->read(&s);switch(index){case 0:return ready;case 1:return s.epoch;case 2:return d->acceptedRouteEpoch;case 3:return (ULONG)InterlockedCompareExchange(&m->callbacks,0,0);case 4:return s.relevant;case 5:return s.polls;case 6:return (ULONG)s.mapHr;case 7:return s.state;case 8:return s.reason;case 9:return (ULONG)InterlockedCompareExchange(&m->ignored,0,0);case 10:return (ULONG)InterlockedCompareExchange(&m->comHr,0,0);}return 0;}
#endif
