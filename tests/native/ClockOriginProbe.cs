using System;
using System.IO;
using System.Collections.Generic;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Threading;
using System.Security.Cryptography;

// Controlled own-process fixture only. Executes the real counter and delta
// functions with substituted imported clock APIs. No game process is opened.
class ClockOriginProbe {
 [DllImport("kernel32",CharSet=CharSet.Unicode)]static extern IntPtr LoadLibrary(string path);
 [DllImport("kernel32")]static extern IntPtr VirtualAlloc(IntPtr p,UIntPtr n,uint type,uint protect);
 [DllImport("kernel32")]static extern bool VirtualProtect(IntPtr p,UIntPtr n,uint protect,out uint old);
 [UnmanagedFunctionPointer(CallingConvention.Cdecl)]delegate void Invoke(IntPtr function,uint cw,IntPtr output);
 static readonly CultureInfo C=CultureInfo.InvariantCulture;
 static int checks;
 static void Check(bool value,string why){Interlocked.Increment(ref checks);if(!value)throw new Exception(why);}
 static void Write(IntPtr p,byte[] bytes){uint old,ignore;Check(VirtualProtect(p,(UIntPtr)bytes.Length,0x40,out old),"protect");Marshal.Copy(bytes,0,p,bytes.Length);VirtualProtect(p,(UIntPtr)bytes.Length,old,out ignore);}
 static IntPtr Code(byte[] b){var p=VirtualAlloc(IntPtr.Zero,(UIntPtr)b.Length,0x3000,0x40);Check(p!=IntPtr.Zero,"allocate");Write(p,b);return p;}
 static byte[] CounterCode(IntPtr data){var b=new List<byte>(new byte[]{0x8b,0x54,0x24,4,0xb8});b.AddRange(BitConverter.GetBytes(data.ToInt32()));b.AddRange(new byte[]{0x8b,8,0x89,0x0a,0x8b,0x48,4,0x89,0x4a,4,0xb8,1,0,0,0,0xc2,4,0});return b.ToArray();}
 static string Hash(byte[] b){using(var s=SHA256.Create())return BitConverter.ToString(s.ComputeHash(b)).Replace("-","").ToLowerInvariant();}
 static double ReadDouble(IntPtr p,int offset){var b=new byte[8];Marshal.Copy(IntPtr.Add(p,offset),b,0,8);return BitConverter.ToDouble(b,0);}
 static Invoke invoke;static IntPtr module,output,data,qpf,qpc,failQpf,failQpc,tick;
 static bool candidate;
 static void Reset(){if(candidate)Marshal.Copy(new byte[16],0,IntPtr.Add(module,0x134000),16);Marshal.WriteByte(module,0x11935c,0);}
 static double Call(int rva,uint cw,IntPtr result){invoke(IntPtr.Add(module,rva),cw,result);Check(ReadDouble(result,8)==1,"x87 sentinel");Check((uint)(ushort)Marshal.ReadInt16(result,16)==cw,"x87 control word");Check(Marshal.ReadInt32(result,20)==0x11223344&&Marshal.ReadInt32(result,24)==0x55667788&&Marshal.ReadInt32(result,28)==0x22334455,"nonvolatile registers");return ReadDouble(result,0);}
 static double Call(int rva,uint cw){return Call(rva,cw,output);}
 static void Iat(int rva,IntPtr p){Write(IntPtr.Add(module,rva),BitConverter.GetBytes(p.ToInt32()));}
 static void Clock(long ticks){Marshal.WriteInt64(data,ticks);}
 static int Main(string[] args){try{
  Check(IntPtr.Size==4,"x86 fixture required");candidate=args[1]=="candidate";
  string path=Path.GetFullPath(args[0]);string expected=candidate?"cb3a69c9555912ee29d06ef65f6094ca6ef861c86a20b4aaefbf2f5c50a87578":"3c524e1f254a1c4f33a30e984ffeb2ad462cb22e71d8af6fa895f74899785c07";
  Check(Hash(File.ReadAllBytes(path))==expected,"file identity");
  if(Array.IndexOf(args,"relocated")>=0)Check(VirtualAlloc(new IntPtr(0x10000000),(UIntPtr)0x200000,0x2000,1)==new IntPtr(0x10000000),"reserve preferred address");
  module=LoadLibrary(path);Check(module!=IntPtr.Zero,"load Base");
  Console.WriteLine("Base=0x"+module.ToInt32().ToString("x8")+" candidate="+candidate+" sha="+expected);
  data=Marshal.AllocHGlobal(32);output=Marshal.AllocHGlobal(32);Marshal.Copy(new byte[32],0,data,32);
  Marshal.WriteInt64(data,8,10000000);qpc=Code(CounterCode(data));qpf=Code(CounterCode(IntPtr.Add(data,8)));
  failQpf=Code(new byte[]{0x31,0xc0,0xc2,4,0});failQpc=failQpf;
  var tb=new List<byte>(new byte[]{0xa1});tb.AddRange(BitConverter.GetBytes(IntPtr.Add(data,16).ToInt32()));tb.Add(0xc3);tick=Code(tb.ToArray());
  Iat(0xac27c,qpc);Iat(0xac278,qpf);Iat(0xac280,tick);
  // Preserve caller CW; set requested CW, retain x87 sentinel below return,
  // inspect callee-saved registers, then restore the fixture's original CW.
  byte[] thunk= new byte[]{0x53,0x56,0x57,0x55,0x83,0xec,8,0xd9,0x3c,0x24,0x66,0x8b,0x44,0x24,32,0x66,0x89,0x44,0x24,2,0xd9,0x6c,0x24,2,0x8b,0x74,0x24,36,0x8b,0x44,0x24,28,0xbb,0x44,0x33,0x22,0x11,0xbf,0x88,0x77,0x66,0x55,0xbd,0x55,0x44,0x33,0x22,0xd9,0xe8,0xff,0xd0,0xdd,0x1e,0xdd,0x5e,8,0xd9,0x7e,16,0x89,0x5e,20,0x89,0x7e,24,0x89,0x6e,28,0xd9,0x2c,0x24,0x83,0xc4,8,0x5d,0x5f,0x5e,0x5b,0xc3};
  invoke=(Invoke)Marshal.GetDelegateForFunctionPointer(Code(thunk),typeof(Invoke));
  Console.WriteLine("uptime_seconds,cw,hz,wall_seconds,game_seconds,ratio");
  double maxError=0;int replay=0;
  foreach(uint cw in new uint[]{0x27f,0x7f})foreach(double uptime in new double[]{0,10,843.203451,483289.2850013,604800,4194304,315360000})foreach(int hz in new int[]{30,50,60,100}){
   Reset();long origin=(long)Math.Round(uptime*10000000);Clock(origin);Call(0x26500,cw);
   double sum=0;for(int i=1;i<=hz*30;i++){Clock(origin+(long)Math.Round(i*10000000.0/hz));sum+=Call(0x26500,cw);}
   double ratio=sum/30;maxError=Math.Max(maxError,Math.Abs(1-ratio));replay++;
   if(candidate)Check(Math.Abs(1-ratio)<.001,"biased game delta uptime="+uptime+" cw="+cw+" hz="+hz+" ratio="+ratio);
   Console.WriteLine(String.Format(C,"{0:F6},0x{1:x},{2},30,{3:F9},{4:F9}",uptime,cw,hz,sum,ratio));
  }
  if(candidate){
   // Exact same clock sequence must return identical session-relative values
   // regardless of OS counter magnitude, including crossing a low-DWORD carry.
   foreach(uint cw in new uint[]{0x27f,0x7f}){
    double[] reference=null;
    foreach(long origin in new long[]{0,0xffffffffL-50000,4832892850013L,3153600000000000L}){
     Reset();Clock(origin);Check(Call(0x26370,cw)==0,"new epoch starts at zero");
     double[] values=new double[1001];
     for(int i=0;i<=1000;i++){Clock(origin+i*123457L);values[i]=Call(0x26370,cw);}
     if(reference==null)reference=values;else for(int i=0;i<values.Length;i++)Check(values[i]==reference[i],"counter origin invariance");
    }
   }
   // Both fallback routes use unsigned modular milliseconds across 49-day wrap.
   foreach(bool qpcFails in new bool[]{false,true}){
    Iat(0xac278,qpcFails?qpf:failQpf);Iat(0xac27c,qpcFails?failQpc:qpc);
    foreach(uint start in new uint[]{0,0xfffffff0,483289285}){
     Reset();Marshal.WriteInt32(data,16,unchecked((int)start));Check(Call(0x26370,0x27f)==0,"fallback epoch");
     foreach(uint delta in new uint[]{1,17,32,1000,30000}){Marshal.WriteInt32(data,16,unchecked((int)(start+delta)));Check(Math.Abs(Call(0x26370,0x27f)-delta/1000.0)<1e-9,"fallback unsigned delta/wrap");}
    }
   }
   Iat(0xac278,qpf);Iat(0xac27c,qpc);
   // Concurrent first publication, stable mock QPC. No fixture hooks call
   // managed delegates. Native code preserves the chosen x87 CW for each call.
   for(int round=0;round<10;round++){
    Reset();Clock(4832892850013L);var gate=new ManualResetEvent(false);var done=new List<Thread>();Exception error=null;
    for(int t=0;t<8;t++){var thread=new Thread(delegate(){IntPtr own=Marshal.AllocHGlobal(32);try{gate.WaitOne();for(int i=0;i<2000;i++)if(Call(0x26370,0x27f,own)!=0)throw new Exception("concurrent epoch drift");}catch(Exception e){error=e;}finally{Marshal.FreeHGlobal(own);}});done.Add(thread);thread.Start();}
    gate.Set();foreach(Thread thread in done)thread.Join();gate.Dispose();Check(error==null,"concurrent publication: "+error);
    Clock(4832892850013L+10000000);Check(Math.Abs(Call(0x26370,0x27f)-1)<1e-12,"shared epoch after concurrent publication");
   }
  }
  Console.WriteLine(String.Format(C,"PASS checks={0}; replays={1}; maximum_mean_ratio_error={2:R}; native ABI/x87 sentinel/control word checked; candidate={3}",checks,replay,maxError,candidate));
  return 0;
 }catch(Exception e){Console.Error.WriteLine(e);return 1;}}
}
