using System;
using System.Runtime.InteropServices;
class CrashHookNoMonitorProbe {
 [DllImport("kernel32",CharSet=CharSet.Unicode,SetLastError=true)]static extern IntPtr LoadLibrary(string path);
 [DllImport("kernel32",CharSet=CharSet.Ansi)]static extern IntPtr GetProcAddress(IntPtr mod,string name);
 [DllImport("kernel32")]static extern bool FreeLibrary(IntPtr mod);
 [UnmanagedFunctionPointer(CallingConvention.StdCall)]delegate uint Version();
 [UnmanagedFunctionPointer(CallingConvention.StdCall)]delegate uint Initialize(IntPtr unused);
 static void Need(bool b,string s){if(!b)throw new Exception(s);}
 static int Main(string[] args){string prior=Environment.GetEnvironmentVariable("BROTHER_DIAG_TOKEN");try{
  Need(IntPtr.Size==4,"x86");
  foreach(string token in new[]{null,"../../bad",Guid.NewGuid().ToString("D")}){
   Environment.SetEnvironmentVariable("BROTHER_DIAG_TOKEN",token);IntPtr m=LoadLibrary(args[0]);Need(m!=IntPtr.Zero,"load "+Marshal.GetLastWin32Error());
   var v=(Version)Marshal.GetDelegateForFunctionPointer(GetProcAddress(m,"DIAG_GetVersion"),typeof(Version));var init=(Initialize)Marshal.GetDelegateForFunctionPointer(GetProcAddress(m,"DIAG_Initialize"),typeof(Initialize));
   Need(v()==1,"version");Need(init(IntPtr.Zero)==0,"absent monitor disables");Need(init(IntPtr.Zero)==0,"disabled repeated initialization remains harmless");Need(FreeLibrary(m),"uninitialized DLL safe unload");Console.WriteLine("PASS token={0} version1 init0 repeated0 unload",token??"<missing>");
  }
  Console.WriteLine("RESULT PASS no monitor/invalid token/missing mapping");return 0;
 }catch(Exception e){Console.WriteLine("RESULT FAIL "+e);return 1;}finally{Environment.SetEnvironmentVariable("BROTHER_DIAG_TOKEN",prior);}}
}
