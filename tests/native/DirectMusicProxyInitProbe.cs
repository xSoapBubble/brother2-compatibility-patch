using System;
using System.IO;
using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.Win32;
using System.Threading;

// Own-process, hidden window, no Play / media / endpoint change.
// Executes actual DirectMusicPerformance::Init with native or proxy DS7.
class DirectMusicProxyInitProbe {
 [DllImport("kernel32",CharSet=CharSet.Unicode)] static extern IntPtr LoadLibraryW(string path);
 [DllImport("kernel32",CharSet=CharSet.Ansi)] static extern IntPtr GetProcAddress(IntPtr m,string name);
 [DllImport("ole32")] static extern int CoInitializeEx(IntPtr p,uint mode);
 [DllImport("ole32")] static extern void CoUninitialize();
 [DllImport("ole32")] static extern int CoCreateInstance(ref Guid cls,IntPtr outer,uint context,ref Guid iid,out IntPtr result);
 [DllImport("user32",CharSet=CharSet.Unicode)] static extern IntPtr CreateWindowExW(uint ex,string cls,string title,uint style,int x,int y,int w,int h,IntPtr parent,IntPtr menu,IntPtr instance,IntPtr data);
 [DllImport("user32")] static extern bool DestroyWindow(IntPtr hwnd);
 [DllImport("dsound")] static extern int DirectSoundCreate(IntPtr guid,out IntPtr ds,IntPtr outer);
 [DllImport("kernel32")] static extern bool GetProcessHandleCount(IntPtr process,out uint count);
 [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int ProxyFactory(IntPtr guid,out IntPtr ds,IntPtr outer);
 [UnmanagedFunctionPointer(CallingConvention.Cdecl,CharSet=CharSet.Unicode)] delegate bool Bind([MarshalAs(UnmanagedType.LPWStr)] string key);
 [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate uint Status(IntPtr device,uint index);
 [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int ForceLoss(IntPtr device);
 [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int Coop(IntPtr self,IntPtr hwnd,uint flags);
 [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate uint Ref(IntPtr self);
 [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int Init(IntPtr self,out IntPtr music,IntPtr ds,IntPtr hwnd);
 [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int Close(IntPtr self);
 static T Com<T>(IntPtr obj,int slot) {return (T)(object)Marshal.GetDelegateForFunctionPointer(Marshal.ReadIntPtr(Marshal.ReadIntPtr(obj),slot*4),typeof(T));}
 static T Export<T>(IntPtr m,string name) {IntPtr p=GetProcAddress(m,name);if(p==IntPtr.Zero)throw new Exception("Missing export "+name);return (T)(object)Marshal.GetDelegateForFunctionPointer(p,typeof(T));}
 static void Hr(int hr,string label) {Console.WriteLine(label+" hr=0x"+hr.ToString("x8"));if(hr<0)throw new Exception(label+" failed");}
 static void Release(ref IntPtr obj) {if(obj==IntPtr.Zero)return;IntPtr p=obj;obj=IntPtr.Zero;Com<Ref>(p,2)(p);}
 [STAThread] static int Main(string[] args) {
  IntPtr ds=IntPtr.Zero,music=IntPtr.Zero,perf=IntPtr.Zero,hwnd=IntPtr.Zero;bool com=false,initialized=false;string key=null;
  try {
   bool proxy=args.Length>0&&args[0]=="proxy";
   Hr(CoInitializeEx(IntPtr.Zero,2),"CoInitializeEx STA");com=true;
   hwnd=CreateWindowExW(0,"STATIC","Brother isolated DirectMusic ABI probe",0x80000000,0,0,32,32,IntPtr.Zero,IntPtr.Zero,IntPtr.Zero,IntPtr.Zero);
   if(hwnd==IntPtr.Zero)throw new Exception("Hidden window creation failed");
   IntPtr helper=IntPtr.Zero;Status status=null;ProxyFactory factory=null;int cycles=args.Length>2?int.Parse(args[2]):1;if(cycles<1||cycles>30)throw new Exception("Invalid cycles");
   if(proxy) {
    helper=LoadLibraryW(Path.GetFullPath(args[1]));if(helper==IntPtr.Zero)throw new Exception("Test helper load failed");
    key=@"Software\Russobit\Brother\REA_Audio_Test_"+Process.GetCurrentProcess().Id;
    if(!Export<Bind>(helper,"REA_TestSetRegistryKey")(key))throw new Exception("Own PID test binding rejected");
    factory=Export<ProxyFactory>(helper,"REA_DirectSoundCreate");
    status=Export<Status>(helper,"REA_TestDeviceStatus");
   }
   for(int cycle=0;cycle<cycles;cycle++) {
   if(proxy)Hr(factory(IntPtr.Zero,out ds,IntPtr.Zero),"Proxy DirectSoundCreate");else Hr(DirectSoundCreate(IntPtr.Zero,out ds,IntPtr.Zero),"Native DirectSoundCreate");
   Hr(Com<Coop>(ds,6)(ds,hwnd,2),"DS7 SetCooperativeLevel PRIORITY");
   Guid cls=new Guid("d2ac2881-b39b-11d1-8704-00600893b1bd"),iid=new Guid("07d43d03-6523-11d2-871d-00600893b1bd");
   Hr(CoCreateInstance(ref cls,IntPtr.Zero,3,ref iid,out perf),"Actual DirectMusicPerformance CoCreateInstance");
   Console.WriteLine("PERF Init begin");
   Hr(Com<Init>(perf,3)(perf,out music,ds,IntPtr.Zero),"Actual Performance::Init(DS7 supplied, HWND null)");initialized=true;
   if(music==IntPtr.Zero)throw new Exception("Performance Init returned no IDirectMusic");
   if(proxy)Console.WriteLine("PROXY generation="+status(ds,0)+" buffers="+status(ds,5)+" groups="+status(ds,6));
   Hr(Com<Close>(perf,38)(perf),"Actual Performance::CloseDown");initialized=false;
   Release(ref music);Release(ref perf);
   if(proxy)Console.WriteLine("AFTER CloseDown buffers="+status(ds,5)+" groups="+status(ds,6));
   Release(ref ds);
   Thread.Sleep(100);int threads;using(Process process=Process.GetCurrentProcess()){threads=process.Threads.Count;}uint handles;GetProcessHandleCount(new IntPtr(-1),out handles);Console.WriteLine("RESOURCES cycle="+cycle+" threads="+threads+" handles="+handles);
   }
   Console.WriteLine("RESULT PASS mode="+(proxy?"proxy":"native")+" cycles="+cycles+" actualInitAndCloseDown noPlay");return 0;
  } catch(Exception e) {Console.Error.WriteLine(e);return 1;}
  finally {
   if(initialized&&perf!=IntPtr.Zero)try{Com<Close>(perf,38)(perf);}catch{}
   Release(ref music);Release(ref perf);Release(ref ds);
   if(hwnd!=IntPtr.Zero)DestroyWindow(hwnd);
   if(com)CoUninitialize();
   if(key!=null)try{Registry.CurrentUser.DeleteSubKeyTree(key,false);Console.WriteLine("CLEANUP ownPIDtestkey");}catch(Exception e){Console.WriteLine("CLEANUP_FAIL "+e.Message);}
  }
 }
}
