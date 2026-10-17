using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;
using Microsoft.Win32;

// Silent real-COM integration. Play is restricted to a separate all-zero PCM
// voice at -10000dB; patterned verification buffers are never played.
// No primary SetFormat or endpoint changes.
// Forced loss/failure APIs exist only in the test helper. Settings use own PID key.
internal static class AudioDeviceProxyProbe
{
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern IntPtr LoadLibraryW(string path);
    [DllImport("kernel32.dll",CharSet=CharSet.Ansi)] static extern IntPtr GetProcAddress(IntPtr module,string name);
    [DllImport("kernel32.dll")] static extern bool FreeLibrary(IntPtr module);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode)] static extern IntPtr CreateEventW(IntPtr sa,bool manual,bool initial,string name);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
    [DllImport("kernel32.dll")] static extern bool ResetEvent(IntPtr handle);
    [DllImport("kernel32.dll")] static extern uint WaitForSingleObject(IntPtr handle,uint milliseconds);
    [DllImport("user32.dll")] static extern IntPtr GetDesktopWindow();
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int Factory(IntPtr guid,out IntPtr device,IntPtr outer);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int BadFactory(IntPtr guid,IntPtr output,IntPtr outer);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl,CharSet=CharSet.Unicode)] delegate bool Bind([MarshalAs(UnmanagedType.LPWStr)]string key);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int ForceLoss(IntPtr device);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int FailRebuild(IntPtr device,int step,int hr);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate uint DeviceStatus(IntPtr device,uint index);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int ReadNativePcm(IntPtr buffer,uint offset,IntPtr data,uint bytes);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int NativeStatus(IntPtr buffer,out uint value);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int NativeCursor(IntPtr buffer,out uint play,out uint write);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int NativeValue(IntPtr buffer,out int value);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int Native3d(IntPtr iface,IntPtr parameters,uint isListener);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int RouteSet(IntPtr device,IntPtr guid,uint state);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int RouteGuids(IntPtr device,out Guid accepted,out Guid observed);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int RouteEvent(IntPtr device,uint kind);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int Query(IntPtr self,ref Guid iid,out IntPtr result);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate uint Ref(IntPtr self);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int Coop(IntPtr self,IntPtr window,uint flags);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int CreateBuffer(IntPtr self,IntPtr desc,out IntPtr buffer,IntPtr outer);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int Duplicate(IntPtr self,IntPtr source,out IntPtr duplicate);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int GetStruct(IntPtr self,IntPtr data);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int GetFormat(IntPtr self,IntPtr data,uint bytes,out uint written);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int SetStruct(IntPtr self,IntPtr data,uint flags);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int SetInt(IntPtr self,int value);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int GetInt(IntPtr self,out int value);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int GetCursor(IntPtr self,out uint play,out uint write);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int Lock(IntPtr self,uint offset,uint count,out IntPtr first,out uint firstCount,out IntPtr second,out uint secondCount,uint flags);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int Unlock(IntPtr self,IntPtr first,uint firstCount,IntPtr second,uint secondCount);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int Notify(IntPtr self,uint count,IntPtr positions);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int Position(IntPtr self,float x,float y,float z,uint flags);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int Simple(IntPtr self);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int Play(IntPtr self,uint reserved,uint priority,uint flags);

    static IntPtr module,device,primary,listener,prototype,duplicate,notify2d,sound3d,spatial,notify3d;
    static IntPtr format,event2d,event3d;
    static IntPtr zeroVoice,zeroNotify,zeroEvent;
    static Factory factory; static ForceLoss force; static FailRebuild fail; static DeviceStatus status;
    static ReadNativePcm readNative; static NativeStatus nativeStatus; static NativeCursor nativeCursor;
    static NativeValue nativeVolume,nativePan; static NativeStatus nativeFrequency; static Native3d native3d;
    static RouteSet setRoute; static RouteGuids routeGuids; static RouteEvent routeEvent; static DeviceStatus routeStatus;
    static bool testRoutes;
    static int checks,cases; static byte[] expectedPcm,expected3dPcm;
    static readonly Guid Unknown=new Guid("00000000-0000-0000-c000-000000000046");
    static readonly Guid Listener=new Guid("279afa84-4981-11ce-a521-0020af0be560");
    static readonly Guid Spatial=new Guid("279afa86-4981-11ce-a521-0020af0be560");
    static readonly Guid Notification=new Guid("b0210783-89cd-11d0-af08-00a0c925cd16");
    const int BufferBytes=16384;
    static void Check(bool ok,string why) {Interlocked.Increment(ref checks);if(!ok)throw new InvalidOperationException(why);}
    static void Hr(int hr,string why) {Check(hr>=0,why+" HRESULT=0x"+hr.ToString("x8"));}
    static void Pass(string name) {cases++;Console.WriteLine("PASS "+name);}
    static T Export<T>(string name) {IntPtr p=GetProcAddress(module,name);Check(p!=IntPtr.Zero,"Missing export "+name);return(T)(object)Marshal.GetDelegateForFunctionPointer(p,typeof(T));}
    static T Com<T>(IntPtr obj,int slot) {Check(obj!=IntPtr.Zero,"NULL COM interface");return(T)(object)Marshal.GetDelegateForFunctionPointer(Marshal.ReadIntPtr(Marshal.ReadIntPtr(obj),slot*4),typeof(T));}
    static IntPtr Zero(int size) {IntPtr p=Marshal.AllocHGlobal(size);Marshal.Copy(new byte[size],0,p,size);return p;}
    static void F(IntPtr p,int offset,float value) {Marshal.WriteInt32(p,offset,BitConverter.ToInt32(BitConverter.GetBytes(value),0));}
    static float F(IntPtr p,int offset) {return BitConverter.ToSingle(BitConverter.GetBytes(Marshal.ReadInt32(p,offset)),0);}
    static IntPtr Q(IntPtr obj,Guid iid) {IntPtr result;Hr(Com<Query>(obj,0)(obj,ref iid,out result),"QueryInterface "+iid);Check(result!=IntPtr.Zero,"QI NULL result");return result;}
    static void Release(ref IntPtr obj) {if(obj==IntPtr.Zero)return;IntPtr p=obj;obj=IntPtr.Zero;Com<Ref>(p,2)(p);}
    static void Identity(IntPtr obj,IntPtr alias) {IntPtr a=Q(obj,Unknown),b=Q(alias,Unknown);Check(a==b,"Canonical IUnknown identity");Release(ref a);Release(ref b);}
    static int Get(IntPtr obj,int slot) {int value;Hr(Com<GetInt>(obj,slot)(obj,out value),"Get slot "+slot);return value;}
    static void Set(IntPtr obj,int slot,int value) {Hr(Com<SetInt>(obj,slot)(obj,value),"Set slot "+slot);}
    static IntPtr MakeBuffer(uint flags,bool isPrimary)
    {
        IntPtr desc=Zero(36),result;
        try {Marshal.WriteInt32(desc,0,36);Marshal.WriteInt32(desc,4,unchecked((int)flags));
            if(!isPrimary){Marshal.WriteInt32(desc,8,BufferBytes);Marshal.WriteIntPtr(desc,16,format);}
            Hr(Com<CreateBuffer>(device,3)(device,desc,out result,IntPtr.Zero),"CreateSoundBuffer flags="+flags.ToString("x"));Check(result!=IntPtr.Zero,"NULL sound buffer");return result;
        } finally {Marshal.FreeHGlobal(desc);}
    }
    static void Caps(IntPtr buffer,uint expected)
    {
        IntPtr caps=Zero(20);try{Marshal.WriteInt32(caps,20);Hr(Com<GetStruct>(buffer,3)(buffer,caps),"GetCaps");uint actual=unchecked((uint)Marshal.ReadInt32(caps,4));Check((actual&expected)==expected,"Buffer caps retained expected="+expected.ToString("x")+" got="+actual.ToString("x"));}finally{Marshal.FreeHGlobal(caps);}
    }
    static void NotifyPositions(IntPtr notification,IntPtr ev)
    {
        IntPtr positions=Zero(16);try{Marshal.WriteInt32(positions,0,256);Marshal.WriteIntPtr(positions,4,ev);Marshal.WriteInt32(positions,8,-1);Marshal.WriteIntPtr(positions,12,ev);Hr(Com<Notify>(notification,3)(notification,2,positions),"SetNotificationPositions");}finally{Marshal.FreeHGlobal(positions);}
    }
    static void WritePcm(IntPtr buffer,int offset,byte[] data)
    {
        IntPtr first,second;uint n1,n2;Hr(Com<Lock>(buffer,11)(buffer,(uint)offset,(uint)data.Length,out first,out n1,out second,out n2,0),"Lock PCM write");
        try{Check(n1+n2==data.Length,"Lock byte count");if(n1>0)Marshal.Copy(data,0,first,(int)n1);if(n2>0)Marshal.Copy(data,(int)n1,second,(int)n2);}finally{Hr(Com<Unlock>(buffer,19)(buffer,first,n1,second,n2),"Unlock PCM write");}
    }
    static byte[] ReadPcm(IntPtr buffer)
    {
        IntPtr first,second;uint n1,n2;byte[] data=new byte[BufferBytes];Hr(Com<Lock>(buffer,11)(buffer,0,BufferBytes,out first,out n1,out second,out n2,0),"Lock PCM read");
        try{Check(n1+n2==data.Length,"Read PCM byte count");if(n1>0)Marshal.Copy(first,data,0,(int)n1);if(n2>0)Marshal.Copy(second,data,(int)n1,(int)n2);}finally{Hr(Com<Unlock>(buffer,19)(buffer,first,n1,second,n2),"Unlock PCM read");}return data;
    }
    static void PcmEquals(IntPtr buffer) {PcmEquals(buffer,expectedPcm);}
    static void PcmEquals(IntPtr buffer,byte[] expected)
    {
        byte[] actual=ReadPcm(buffer);for(int i=0;i<actual.Length;i++)Check(actual[i]==expected[i],"Shadow PCM mismatch at "+i);
        IntPtr bytes=Zero(expected.Length);try{Hr(readNative(buffer,0,bytes,(uint)expected.Length),"Independent native PCM read");Marshal.Copy(bytes,actual,0,actual.Length);for(int i=0;i<actual.Length;i++)Check(actual[i]==expected[i],"Actual native PCM mismatch at "+i);}finally{Marshal.FreeHGlobal(bytes);}
    }
    static void FormatState(IntPtr buffer)
    {
        IntPtr p=Zero(18);try{uint written;Hr(Com<GetFormat>(buffer,5)(buffer,p,18,out written),"GetFormat");Check(written==18&&Marshal.ReadInt16(p,0)==1&&Marshal.ReadInt16(p,2)==1&&Marshal.ReadInt32(p,4)==22050&&Marshal.ReadInt16(p,14)==16,"PCM format retained");}finally{Marshal.FreeHGlobal(p);}
    }
    static IntPtr ListenerData()
    {
        IntPtr p=Zero(64);Marshal.WriteInt32(p,64);F(p,4,1);F(p,8,2);F(p,12,3);F(p,16,.25f);F(p,20,.5f);F(p,24,.75f);F(p,28,1);F(p,44,1);F(p,52,2.5f);F(p,56,.75f);F(p,60,1.25f);return p;
    }
    static IntPtr SpatialData()
    {
        IntPtr p=Zero(64);Marshal.WriteInt32(p,64);F(p,4,4);F(p,8,5);F(p,12,6);Marshal.WriteInt32(p,28,180);Marshal.WriteInt32(p,32,270);F(p,44,1);Marshal.WriteInt32(p,48,-900);F(p,52,2);F(p,56,1000);return p;
    }
    static void SpatialState()
    {
        IntPtr p=Zero(64);try{Marshal.WriteInt32(p,64);Hr(Com<GetStruct>(listener,3)(listener,p),"Listener GetAllParameters");Check(F(p,4)==-1&&F(p,8)==4&&F(p,12)==8,"Listener position retained");Check(F(p,52)==2.5f&&F(p,56)==.75f&&F(p,60)==1.25f,"Listener factors retained");
            Marshal.Copy(new byte[64],0,p,64);Marshal.WriteInt32(p,64);Hr(Com<GetStruct>(spatial,3)(spatial,p),"3D buffer GetAllParameters");Check(F(p,4)==7&&F(p,8)==8&&F(p,12)==9,"3D position retained");Check(Marshal.ReadInt32(p,28)==180&&Marshal.ReadInt32(p,32)==270&&Marshal.ReadInt32(p,48)==-900,"3D cone state retained");Check(F(p,52)==2&&F(p,56)==1000&&Marshal.ReadInt32(p,60)==0,"3D distance/mode retained");
            Marshal.Copy(new byte[64],0,p,64);Marshal.WriteInt32(p,64);Hr(native3d(listener,p,1),"Actual native listener GetAllParameters");Check(F(p,4)==-1&&F(p,8)==4&&F(p,12)==8,"Actual native listener position retained");Check(F(p,52)==2.5f&&F(p,56)==.75f&&F(p,60)==1.25f,"Actual native listener factors retained");Check(F(p,16)==.25f&&F(p,20)==.5f&&F(p,24)==.75f&&F(p,28)==1&&F(p,36)==0&&F(p,44)==1,"Actual native listener velocity/orientation retained");
            Marshal.Copy(new byte[64],0,p,64);Marshal.WriteInt32(p,64);Hr(native3d(spatial,p,0),"Actual native spatial GetAllParameters");Check(F(p,4)==7&&F(p,8)==8&&F(p,12)==9,"Actual native spatial position retained");Check(Marshal.ReadInt32(p,28)==180&&Marshal.ReadInt32(p,32)==270&&Marshal.ReadInt32(p,48)==-900,"Actual native cone state retained");Check(F(p,52)==2&&F(p,56)==1000&&Marshal.ReadInt32(p,60)==0,"Actual native spatial distance/mode retained");
        }finally{Marshal.FreeHGlobal(p);}
    }
    static void Cursor(IntPtr buffer,uint expected) {uint play,write;Hr(Com<GetCursor>(buffer,4)(buffer,out play,out write),"GetCurrentPosition");Check(play==expected,"Stopped play cursor retained expected="+expected+" got="+play);Hr(nativeCursor(buffer,out play,out write),"Actual native stopped cursor");Check(play==expected,"Actual native stopped cursor retained expected="+expected+" got="+play);}
    static void NeverPlaying(IntPtr buffer) {Check((Get(buffer,9)&1)==0,"Patterned buffer must never play");uint flags;Hr(nativeStatus(buffer,out flags),"Native stopped status");Check((flags&1)==0,"Actual patterned native buffer must never play");}
    static void CurrentState()
    {
        int actual;Hr(nativeVolume(duplicate,out actual),"Actual native 2D volume");Check(actual==-700,"Actual native 2D volume retained");Hr(nativeVolume(sound3d,out actual),"Actual native 3D volume");Check(actual==-900,"Actual native 3D volume retained");Hr(nativePan(duplicate,out actual),"Actual native 2D pan");Check(actual==-1500,"Actual native 2D pan retained");uint frequency;Hr(nativeFrequency(duplicate,out frequency),"Actual native 2D frequency");Check(frequency==16000,"Actual native 2D frequency retained");Hr(nativeFrequency(sound3d,out frequency),"Actual native 3D frequency");Check(frequency==18000,"Actual native 3D frequency retained");
        Check(Get(duplicate,6)==-700,"2D volume retained");Check(Get(duplicate,7)==-1500,"2D pan retained");Check(Get(duplicate,8)==16000,"2D frequency retained");Cursor(duplicate,512);Caps(duplicate,0x1e0);PcmEquals(duplicate);FormatState(duplicate);NeverPlaying(duplicate);
        Check(Get(sound3d,6)==-900,"3D volume retained");Check(Get(sound3d,8)==18000,"3D frequency retained");Cursor(sound3d,1024);Caps(sound3d,0x1b0);PcmEquals(sound3d,expected3dPcm);FormatState(sound3d);NeverPlaying(sound3d);SpatialState();
        IntPtr a=Q(primary,Listener),b=Q(duplicate,Notification),c=Q(sound3d,Spatial),d=Q(sound3d,Notification);
        Check(a==listener&&b==notify2d&&c==spatial&&d==notify3d,"Stable interface pointers across generations");Release(ref a);Release(ref b);Release(ref c);Release(ref d);
        Identity(primary,listener);Identity(sound3d,spatial);Identity(duplicate,notify2d);
    }
    static void DeviceCapsCall(bool requireSuccess)
    {
        IntPtr caps=Zero(96);try{Marshal.WriteInt32(caps,96);int hr=Com<GetStruct>(device,4)(device,caps);if(requireSuccess)Hr(hr,"Device GetCaps/rebuild");else Console.WriteLine("STAGED_FAILURE callerHRESULT=0x"+hr.ToString("x8"));}finally{Marshal.FreeHGlobal(caps);}
    }
    static void BuildInitial()
    {
        Hr(factory(IntPtr.Zero,out device,IntPtr.Zero),"cdecl factory");Check(device!=IntPtr.Zero,"Factory result");Check(status(device,0)==1,"Initial generation1");Identity(device,device);
        Hr(Com<Coop>(device,6)(device,GetDesktopWindow(),1),"DSSCL_NORMAL only");
        format=Zero(18);Marshal.WriteInt16(format,0,1);Marshal.WriteInt16(format,2,1);Marshal.WriteInt32(format,4,22050);Marshal.WriteInt32(format,8,44100);Marshal.WriteInt16(format,12,2);Marshal.WriteInt16(format,14,16);
        primary=MakeBuffer(0x11,true);listener=Q(primary,Listener);IntPtr lp=ListenerData();try{Hr(Com<SetStruct>(listener,10)(listener,lp,0),"Listener SetAllParameters");}finally{Marshal.FreeHGlobal(lp);}
        Hr(Com<Position>(listener,14)(listener,-1,4,8,1),"Listener deferred position");Hr(Com<Simple>(listener,17)(listener),"CommitDeferredSettings");
        prototype=MakeBuffer(0x1e0,false);expectedPcm=new byte[BufferBytes];for(int i=0;i<expectedPcm.Length;i++)expectedPcm[i]=(byte)(i*17+3);WritePcm(prototype,0,expectedPcm);
        Hr(Com<Duplicate>(device,5)(device,prototype,out duplicate),"DuplicateSoundBuffer");Check(duplicate!=IntPtr.Zero&&duplicate!=prototype,"Distinct duplicate proxy");PcmEquals(duplicate);
        byte[] change=new byte[200];for(int i=0;i<change.Length;i++)change[i]=(byte)(255-i);WritePcm(duplicate,100,change);Array.Copy(change,0,expectedPcm,100,change.Length);PcmEquals(prototype);
        Release(ref prototype);PcmEquals(duplicate);Set(duplicate,15,-700);Set(duplicate,16,-1500);Set(duplicate,17,16000);Set(duplicate,13,512);
        event2d=CreateEventW(IntPtr.Zero,false,false,null);Check(event2d!=IntPtr.Zero,"Create notification event2D");notify2d=Q(duplicate,Notification);NotifyPositions(notify2d,event2d);
        sound3d=MakeBuffer(0x201b0,false);expected3dPcm=new byte[BufferBytes];for(int i=0;i<expected3dPcm.Length;i++)expected3dPcm[i]=(byte)(i*31+71);WritePcm(sound3d,0,expected3dPcm);spatial=Q(sound3d,Spatial);IntPtr sp=SpatialData();try{Hr(Com<SetStruct>(spatial,12)(spatial,sp,0),"3D SetAllParameters");}finally{Marshal.FreeHGlobal(sp);}
        Hr(Com<Position>(spatial,19)(spatial,7,8,9,0),"3D SetPosition");Set(sound3d,15,-900);Set(sound3d,17,18000);Set(sound3d,13,1024);
        event3d=CreateEventW(IntPtr.Zero,false,false,null);Check(event3d!=IntPtr.Zero,"Create notification event3D");notify3d=Q(sound3d,Notification);NotifyPositions(notify3d,event3d);CurrentState();
        Pass("cdecl factory, primary listener, real 2D/3D, shared duplicate PCM after prototype Release, all stopped state");
    }
    static void Rebuilds()
    {
        for(int i=0;i<5;i++){uint generation=status(device,0),notifications=status(device,11);Hr(force(device),"ForceLoss");Check(status(device,4)==1,"Loss pending");DeviceCapsCall(true);Check(status(device,0)==generation+1&&status(device,4)==0,"Fresh generation committed");Check(status(device,11)>=notifications+2,"Native notification registrations replayed");CurrentState();}
        Pass("five fresh device generations preserve PCM, settings, spatial state and interface identities; notify replay counted");
        foreach(int step in new int[]{0,1}){uint generation=status(device,0),failures=status(device,3);Hr(fail(device,step,unchecked((int)0x80004005)),"Arm staging failure");Hr(force(device),"ForceLoss for staging failure");DeviceCapsCall(false);Check(status(device,0)==generation,"Failed staging cannot publish generation");Check(status(device,3)>failures&&status(device,4)==1,"Failed staging leaves retry pending");Hr(force(device),"Clear retry deadline");DeviceCapsCall(true);Check(status(device,0)==generation+1,"Retry publishes one generation");CurrentState();}
        Pass("staged failure before buffers and mid-build is transactional; next fresh retry restores original proxies");
    }
    static void LockedRebuild()
    {
        IntPtr first,second;uint n1,n2;Hr(Com<Lock>(duplicate,11)(duplicate,0,128,out first,out n1,out second,out n2,0),"Hold shadow Lock");uint generation=status(device,0);try{Check(status(device,9)>0,"Active shadow lock tracked");Hr(force(device),"ForceLoss while locked");DeviceCapsCall(false);Check(status(device,0)==generation&&status(device,4)==1,"Locked group defers generation");}finally{Hr(Com<Unlock>(duplicate,19)(duplicate,first,n1,second,n2),"Unlock held shadow");}Check(status(device,9)==0,"Shadow lock count balanced");DeviceCapsCall(true);Check(status(device,0)==generation+1,"Rebuild after Unlock");CurrentState();Pass("shadow Lock prevents buffer replacement until balanced Unlock");
    }
    static void ZeroVoiceState()
    {
        uint flags,first,ignored,last;
        Hr(nativeStatus(zeroVoice,out flags),"Independent native playing status");Check((flags&5)==5,"Actual zero-PCM voice is playing and looping");
        Hr(nativeCursor(zeroVoice,out first,out ignored),"Native cursor before wait");Thread.Sleep(80);Hr(nativeCursor(zeroVoice,out last,out ignored),"Native cursor after wait");Check(first!=last,"Actual native cursor advances");
        Check(ResetEvent(zeroEvent),"Reset native notification event");Check(WaitForSingleObject(zeroEvent,1500)==0,"Actual native notification delivery after reset");
        Check(Get(zeroVoice,6)==-10000,"Zero PCM voice remains muted");int actual;Hr(nativeVolume(zeroVoice,out actual),"Actual native zero voice volume");Check(actual==-10000,"Actual native zero PCM voice remains muted");PcmEquals(zeroVoice,new byte[BufferBytes]);
    }
    static void ActiveZeroVoice()
    {
        Check(status(device,10)==0,"No Play before explicitly authorized zero-PCM phase");
        zeroVoice=MakeBuffer(0x181a0,false);Set(zeroVoice,15,-10000);WritePcm(zeroVoice,0,new byte[BufferBytes]);PcmEquals(zeroVoice,new byte[BufferBytes]);int actual;Hr(nativeVolume(zeroVoice,out actual),"Actual native pre-Play zero voice volume");Check(actual==-10000,"Verify native mute before Play");
        zeroEvent=CreateEventW(IntPtr.Zero,false,false,null);Check(zeroEvent!=IntPtr.Zero,"Create zero-PCM notify event");zeroNotify=Q(zeroVoice,Notification);NotifyPositions(zeroNotify,zeroEvent);
        Hr(Com<Play>(zeroVoice,12)(zeroVoice,0,0,1),"Play only independently verified all-zero PCM at -10000, looping");ZeroVoiceState();
        for(int i=0;i<3;i++){uint generation=status(device,0);Hr(force(device),"Force loss while zero voice plays");DeviceCapsCall(true);Check(status(device,0)==generation+1,"Active fresh generation");ZeroVoiceState();CurrentState();}
        uint before=status(device,0),failed=status(device,3);Hr(fail(device,1,unchecked((int)0x80004005)),"Arm active staging failure");Hr(force(device),"Force active loss");DeviceCapsCall(false);Check(status(device,0)==before&&status(device,3)>failed,"Active failed staging does not publish");Hr(force(device),"Active retry");DeviceCapsCall(true);Check(status(device,0)==before+1,"Active retry generation");ZeroVoiceState();
        if(testRoutes)RouteMonitoring();
        Hr(Com<Simple>(zeroVoice,18)(zeroVoice),"Stop zero-PCM voice");uint stopped;Hr(nativeStatus(zeroVoice,out stopped),"Native stopped zero voice");Check((stopped&1)==0,"Actual native zero voice stopped");Release(ref zeroNotify);Release(ref zeroVoice);CloseHandle(zeroEvent);zeroEvent=IntPtr.Zero;
        Pass("only all-zero muted PCM played: native PLAYING/looping, advancing cursor and real notifications survive four fresh generations and staging failure");
    }
    static void SetMapped(Guid guid)
    {
        IntPtr p=Zero(16);try{Marshal.StructureToPtr(guid,p,false);Hr(setRoute(device,p,1),"Set only synthetic mapped-route oracle");}finally{Marshal.FreeHGlobal(p);}
    }
    static void RouteSnapshot(out Guid accepted,out Guid observed) {Hr(routeGuids(device,out accepted,out observed),"Read independent committed/observed routes");}
    static void WaitObserved(Guid desired)
    {
        Stopwatch watch=Stopwatch.StartNew();Guid accepted,observed;
        do{RouteSnapshot(out accepted,out observed);if(routeStatus(device,0)!=0&&observed==desired)return;Thread.Sleep(20);}while(watch.ElapsedMilliseconds<5000);
        throw new InvalidOperationException("Route worker did not observe "+desired);
    }
    static void WaitAccepted(Guid desired,uint generation)
    {
        Stopwatch watch=Stopwatch.StartNew();Guid accepted,observed;
        do{DeviceCapsCall(true);RouteSnapshot(out accepted,out observed);if(accepted==desired&&status(device,0)==generation)return;Thread.Sleep(25);}while(watch.ElapsedMilliseconds<6000);
        throw new InvalidOperationException("Ordinary COM did not commit route "+desired+" at generation "+generation);
    }
    static void RouteMonitoring()
    {
        Guid a,observed;Stopwatch ready=Stopwatch.StartNew();
        while(routeStatus(device,0)==0&&ready.ElapsedMilliseconds<5000)Thread.Sleep(20);
        Check(routeStatus(device,0)!=0,"Route monitor worker ready");RouteSnapshot(out a,out observed);
        if(a==Guid.Empty)a=new Guid("01aefcd1-24a3-47f8-b3fa-1f238c7444a1");
        byte[] bits=a.ToByteArray();bits[15]^=0x80;Guid b=new Guid(bits);Check(a!=b,"Synthetic routes distinct");
        // Establish a stable synthetic A fingerprint first. The native factory
        // remains on its real default endpoint; these GUIDs are monitor inputs.
        SetMapped(a);WaitObserved(a);Guid stableAccepted;Stopwatch establish=Stopwatch.StartNew();do{DeviceCapsCall(true);RouteSnapshot(out stableAccepted,out observed);if(stableAccepted==a&&status(device,4)==0)break;Thread.Sleep(25);}while(establish.ElapsedMilliseconds<6000);Check(stableAccepted==a&&status(device,4)==0,"Established healthy synthetic A");ZeroVoiceState();
        uint generation=status(device,0);uint healthy;Hr(nativeStatus(zeroVoice,out healthy),"Healthy native voice before route change");Check((healthy&3)==1,"Playing native voice not BUFFERLOST");
        SetMapped(b);WaitObserved(b);Check(status(device,0)==generation,"Oracle override alone never publishes generation");Guid accepted;RouteSnapshot(out accepted,out observed);Check(accepted==a,"A remains committed until normal COM");
        WaitAccepted(b,generation+1);Check(status(device,4)==0,"B recovered without explicit ForceLoss");ZeroVoiceState();CurrentState();
        generation=status(device,0);SetMapped(a);Hr(routeEvent(device,2),"Queue relevant default change via callback path");WaitObserved(a);WaitAccepted(a,generation+1);ZeroVoiceState();CurrentState();
        Pass("healthy mapped A to B to A detected by worker/ordinary COM with no ForceLoss or BUFFERLOST; real silent voice/native state retained");

        generation=status(device,0);uint ignored=routeStatus(device,9),relevant=routeStatus(device,4);
        Hr(routeEvent(device,3),"Unrelated endpoint state event");Hr(routeEvent(device,4),"Communications-only default event");Hr(routeEvent(device,5),"Unrelated/volume property event");
        Stopwatch drain=Stopwatch.StartNew();while(routeStatus(device,9)<ignored+3&&drain.ElapsedMilliseconds<3000)Thread.Sleep(20);
        Check(routeStatus(device,9)>=ignored+3,"Unrelated event filters counted");DeviceCapsCall(true);RouteSnapshot(out accepted,out observed);Check(status(device,0)==generation&&accepted==a,"Unrelated events do not replace healthy generation");Check(routeStatus(device,4)==relevant,"Unrelated events do not enter relevant callback path");
        Pass("unrelated endpoint state, communications role and volume/property events are ignored without fresh generation");

        generation=status(device,0);uint failures=status(device,3);Hr(fail(device,1,unchecked((int)0x80004005)),"Arm route-change staging failure");SetMapped(b);Hr(routeEvent(device,1),"Queue relevant format notification");WaitObserved(b);DeviceCapsCall(false);RouteSnapshot(out accepted,out observed);
        Check(status(device,0)==generation&&accepted==a,"Failed route staging leaves committed A and generation unchanged");Check(status(device,3)>failures&&status(device,4)==1,"Route failure retry pending");
        // No ForceLoss here: retry deadline expires naturally and ordinary COM
        // re-evaluates the still-observed B route, preventing a self-confirming test.
        WaitAccepted(b,generation+1);ZeroVoiceState();CurrentState();generation=status(device,0);SetMapped(a);Hr(routeEvent(device,0),"Queue relevant ACTIVE event");WaitObserved(a);WaitAccepted(a,generation+1);ZeroVoiceState();
        Pass("failed mapped-route staging keeps A; natural ordinary-COM retry commits B, then restoration to A remains observable");

        Exception workerFailure=null;bool stop=false;
        Thread caller=new Thread(delegate(){try{while(!Volatile.Read(ref stop)){DeviceCapsCall(true);Thread.Sleep(2);}}catch(Exception error){workerFailure=error;}});caller.IsBackground=true;caller.Start();
        try{for(int i=0;i<4;i++){Guid desired=(i%2==0)?b:a;SetMapped(desired);Hr(routeEvent(device,2),"Concurrent relevant notification");WaitObserved(desired);Stopwatch acceptedWait=Stopwatch.StartNew();do{RouteSnapshot(out accepted,out observed);if(accepted==desired)break;Thread.Sleep(20);}while(acceptedWait.ElapsedMilliseconds<5000);Check(accepted==desired,"Concurrent normal COM accepts current observed route");}}
        finally{Volatile.Write(ref stop,true);Check(caller.Join(3000),"COM/event worker stress must not deadlock");}
        Check(workerFailure==null,"Concurrent caller failed: "+workerFailure);RouteSnapshot(out accepted,out observed);Check(accepted==a,"Concurrent monitor ends on A");ZeroVoiceState();CurrentState();
        Hr(setRoute(device,IntPtr.Zero,1),"Clear synthetic mapping override");DeviceCapsCall(true);
        Pass("bounded concurrent callback and ordinary-COM route changes finish without deadlock; original interface/notification lifetime retained");
    }
    static int Main(string[] args)
    {
        string key="Software\\Russobit\\Brother\\REA_Audio_Test_"+Process.GetCurrentProcess().Id;
        try{Check(IntPtr.Size==4,"x86 probe");Check(args.Length>=1&&args.Length<=2,"Usage: AudioDeviceProxyProbe.exe absolute-test-helper.dll [routes]");testRoutes=Array.IndexOf(args,"routes")>=0;module=LoadLibraryW(Path.GetFullPath(args[0]));Check(module!=IntPtr.Zero,"Load test helper "+Marshal.GetLastWin32Error());Check(Export<Bind>("REA_TestSetRegistryKey")(key),"Exact own PID test key bound");factory=Export<Factory>("REA_DirectSoundCreate");force=Export<ForceLoss>("REA_TestDeviceForceLoss");fail=Export<FailRebuild>("REA_TestDeviceFailNextRebuild");status=Export<DeviceStatus>("REA_TestDeviceStatus");readNative=Export<ReadNativePcm>("REA_TestProxyReadNativePCM");nativeStatus=Export<NativeStatus>("REA_TestProxyNativeStatus");nativeCursor=Export<NativeCursor>("REA_TestProxyNativeCursor");nativeVolume=Export<NativeValue>("REA_TestProxyNativeVolume");nativePan=Export<NativeValue>("REA_TestProxyNativePan");nativeFrequency=Export<NativeStatus>("REA_TestProxyNativeFrequency");native3d=Export<Native3d>("REA_TestProxyNative3DParameters");if(testRoutes){setRoute=Export<RouteSet>("REA_TestDeviceSetRoute");routeGuids=Export<RouteGuids>("REA_TestDeviceRouteGUIDs");routeEvent=Export<RouteEvent>("REA_TestDeviceRouteEvent");routeStatus=Export<DeviceStatus>("REA_TestDeviceRouteStatus");}
            int invalid=Export<BadFactory>("REA_DirectSoundCreate")(IntPtr.Zero,IntPtr.Zero,IntPtr.Zero);Check(invalid<0,"NULL factory output rejected");BuildInitial();Rebuilds();LockedRebuild();ActiveZeroVoice();
            uint plays=status(device,10);Check(plays>=5,"Native zero voice initial Play and four resumes counted");Release(ref notify3d);Release(ref spatial);Release(ref sound3d);Release(ref notify2d);Release(ref duplicate);Release(ref listener);Release(ref primary);Check(status(device,5)==0&&status(device,6)==0&&status(device,7)==0,"No live wrappers/groups/PCM after full release");Check(status(device,9)==0,"No remaining shadow locks");uint final=Com<Ref>(device,2)(device);device=IntPtr.Zero;Check(final==0,"Final device proxy Release reaches0");Pass("COM aliases and device/buffer/group lifetimes completely released");if(testRoutes){Hr(factory(IntPtr.Zero,out device,IntPtr.Zero),"Second monitor/device lifetime factory");Stopwatch ready=Stopwatch.StartNew();while(routeStatus(device,0)==0&&ready.ElapsedMilliseconds<5000)Thread.Sleep(20);Check(routeStatus(device,0)!=0,"Second monitor worker ready");Check(status(device,5)==0,"Second lifetime has no inherited wrappers");final=Com<Ref>(device,2)(device);device=IntPtr.Zero;Check(final==0,"Second monitor lifetime fully released");Pass("new device monitor starts and stops after complete previous lifetime teardown");}Console.WriteLine("RESULT PASS cases="+cases+" assertions="+checks+" onlyZeroPcmPlayed=true nativePlayCalls="+plays);return 0;
        }catch(Exception error){Console.WriteLine("RESULT FAIL "+error);return 1;}
        finally{if(zeroVoice!=IntPtr.Zero)Com<Simple>(zeroVoice,18)(zeroVoice);Release(ref zeroNotify);Release(ref zeroVoice);if(zeroEvent!=IntPtr.Zero)CloseHandle(zeroEvent);Release(ref notify3d);Release(ref spatial);Release(ref sound3d);Release(ref notify2d);Release(ref duplicate);Release(ref prototype);Release(ref listener);Release(ref primary);Release(ref device);if(event3d!=IntPtr.Zero)CloseHandle(event3d);if(event2d!=IntPtr.Zero)CloseHandle(event2d);if(format!=IntPtr.Zero)Marshal.FreeHGlobal(format);if(module!=IntPtr.Zero)FreeLibrary(module);try{Registry.CurrentUser.DeleteSubKeyTree(key,false);using(RegistryKey remains=Registry.CurrentUser.OpenSubKey(key))Check(remains==null,"Private PID registry cleanup");Console.WriteLine("CLEANUP own PID test key removed");}catch(Exception error){Console.WriteLine("TEST_KEY_CLEANUP_FAIL "+error);}}
    }
}
