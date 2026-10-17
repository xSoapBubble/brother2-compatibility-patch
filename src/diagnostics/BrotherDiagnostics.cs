// Portable x86 monitor. No debugger, global crash settings or network activity.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.IO.MemoryMappedFiles;
using System.Management;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using Microsoft.Win32;

static class BrotherDiagnostics {
 const uint MAGIC=0x42444941, DUMP_FLAGS=0x1160;
 const string OWNER="BrotherDiagnostics-v2";
 static string folder, bin, reports; static Process game; static IntPtr processHandle;
 static StreamWriter log; static MemoryMappedViewAccessor shared; static EventWaitHandle crash,done;
 static int dumps; static long lastErrorWindow; static bool fixture,reportNeeded,reportPublished;
 static readonly ManualResetEvent inventoryDone=new ManualResetEvent(false);
 static readonly object logLock=new object();
 [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)] struct STARTUPINFO { public uint cb; public string reserved,desktop,title; public uint x,y,w,h,cx,cy,fill,flags; public ushort show,cb2; public IntPtr reserved2,stdin,stdout,stderr; }
 [StructLayout(LayoutKind.Sequential)] struct PROCESS_INFORMATION { public IntPtr process,thread; public uint pid,tid; }
 [StructLayout(LayoutKind.Sequential,Pack=4)] struct DUMP_EXCEPTION { public uint tid; public IntPtr pointers; [MarshalAs(UnmanagedType.Bool)] public bool clientPointers; }
 [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)] struct MODULEENTRY { public uint size,id,pid,globalUse,processUse; public IntPtr baseAddress; public uint baseSize; public IntPtr module; [MarshalAs(UnmanagedType.ByValTStr,SizeConst=256)] public string name; [MarshalAs(UnmanagedType.ByValTStr,SizeConst=260)] public string path; }
 delegate bool EnumWindow(IntPtr window,IntPtr unused);
 [DllImport("kernel32",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool CreateProcessW(string app,StringBuilder cmd,IntPtr pa,IntPtr ta,bool inherit,uint flags,IntPtr environment,string cwd,ref STARTUPINFO startup,out PROCESS_INFORMATION process);
 [DllImport("kernel32",SetLastError=true)] static extern uint ResumeThread(IntPtr thread);
 [DllImport("kernel32",SetLastError=true)] static extern bool CloseHandle(IntPtr h);
 [DllImport("kernel32",SetLastError=true)] static extern IntPtr VirtualAllocEx(IntPtr h,IntPtr address,UIntPtr size,uint type,uint protection);
 [DllImport("kernel32",SetLastError=true)] static extern bool VirtualFreeEx(IntPtr h,IntPtr address,UIntPtr size,uint type);
 [DllImport("kernel32",SetLastError=true)] static extern bool WriteProcessMemory(IntPtr h,IntPtr address,byte[] data,UIntPtr size,out UIntPtr wrote);
 [DllImport("kernel32",SetLastError=true)] static extern bool ReadProcessMemory(IntPtr h,IntPtr address,byte[] data,UIntPtr size,out UIntPtr read);
 [DllImport("kernel32",SetLastError=true)] static extern IntPtr CreateRemoteThread(IntPtr h,IntPtr sa,UIntPtr stack,IntPtr start,IntPtr arg,uint flags,IntPtr tid);
 [DllImport("kernel32")] static extern uint WaitForSingleObject(IntPtr h,uint ms);
 [DllImport("kernel32")] static extern bool GetExitCodeThread(IntPtr h,out uint exit);
 [DllImport("kernel32")] static extern bool GetExitCodeProcess(IntPtr h,out uint exit);
 [DllImport("kernel32",CharSet=CharSet.Unicode)] static extern IntPtr GetModuleHandleW(string name);
 [DllImport("kernel32",CharSet=CharSet.Ansi)] static extern IntPtr GetProcAddress(IntPtr module,string name);
 [DllImport("kernel32",CharSet=CharSet.Unicode,SetLastError=true)] static extern IntPtr LoadLibraryExW(string name,IntPtr file,uint flags);
 [DllImport("kernel32")] static extern bool FreeLibrary(IntPtr module);
 [DllImport("kernel32",SetLastError=true)] static extern IntPtr CreateToolhelp32Snapshot(uint flags,uint pid);
 [DllImport("kernel32",CharSet=CharSet.Unicode)] static extern bool Module32FirstW(IntPtr snap,ref MODULEENTRY item);
 [DllImport("kernel32",CharSet=CharSet.Unicode)] static extern bool Module32NextW(IntPtr snap,ref MODULEENTRY item);
 [DllImport("dbghelp",SetLastError=true)] static extern bool MiniDumpWriteDump(IntPtr process,uint pid,IntPtr file,uint type,IntPtr exception,IntPtr user,IntPtr callback);
 [DllImport("user32")] static extern bool EnumWindows(EnumWindow callback,IntPtr unused);
 [DllImport("user32")] static extern bool EnumChildWindows(IntPtr window,EnumWindow callback,IntPtr unused);
 [DllImport("user32")] static extern uint GetWindowThreadProcessId(IntPtr window,out uint pid);
 [DllImport("user32",CharSet=CharSet.Unicode)] static extern int GetWindowTextW(IntPtr window,StringBuilder text,int count);
 [DllImport("user32")] static extern bool IsHungAppWindow(IntPtr window);
 [DllImport("user32",CharSet=CharSet.Unicode)] static extern int MessageBoxW(IntPtr window,string text,string caption,uint type);

 static void Write(string text) { lock(logLock) { if(log!=null) { try { log.WriteLine(DateTime.UtcNow.ToString("o")+" "+text); log.Flush(); } catch(ObjectDisposedException) {} } } }
 static string Error(string where) { return where+" Win32="+Marshal.GetLastWin32Error(); }
 static bool Exited() { return processHandle!=IntPtr.Zero&&WaitForSingleObject(processHandle,0)==0; }
 static void Require(bool ok,string where) { if(!ok) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(),where); }
 static string Hash(string path) { using(var f=File.Open(path,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete)) using(var sha=SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(f)).Replace("-","").ToLowerInvariant(); }
 static string ReportRoot(string appBin) {
   string preferred=Path.GetFullPath(Path.Combine(appBin,"..","Diagnostics"));
   try { Directory.CreateDirectory(preferred); string p=Path.Combine(preferred,".write-test-"+Guid.NewGuid().ToString("N")); File.WriteAllText(p,"");File.Delete(p);return preferred; }
   catch { string fallback=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Brother","Diagnostics");Directory.CreateDirectory(fallback);return fallback; }
 }
 static void Inventory() {
   Write("monitor.version=2 report.policy=errors-only architecture=x86 os="+Environment.OSVersion+" os64="+Environment.Is64BitOperatingSystem+" runtime="+Environment.Version);
   try {using(var os=Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Microsoft\Windows NT\CurrentVersion"))if(os!=null)Write("windows product="+os.GetValue("ProductName")+" displayVersion="+os.GetValue("DisplayVersion")+" build="+os.GetValue("CurrentBuildNumber")+"."+os.GetValue("UBR"));}catch(Exception e){Write("os.inventory.error "+e.Message);}
   Write("game.directory="+bin+" report.directory="+folder+" debugger=false");
   foreach(string pattern in new[]{"*.exe","*.dll","DDrawCompat.ini","brother.ini","*.sav","*.save_db"}) foreach(string p in Directory.GetFiles(bin,pattern)) {
     try { var fi=new FileInfo(p);Write("file "+fi.Name+" size="+fi.Length+" sha256="+Hash(p)); } catch(Exception e) {Write("file.inventory.error "+Path.GetFileName(p)+" "+e.Message);}
   }
   foreach(string name in new[]{"DDrawCompat.ini","brother.ini"}) CopyTail(Path.Combine(bin,name),Path.Combine(folder,name),65536);
   try { using(var key=Registry.CurrentUser.OpenSubKey(@"Software\Russobit\Brother")) if(key!=null) foreach(string name in key.GetValueNames()) {object v=key.GetValue(name);var bytes=v as byte[];Write("game.setting "+name+"="+(bytes==null?Convert.ToString(v):BitConverter.ToString(bytes)));} } catch(Exception e){Write("settings.error "+e.Message);}
   try { using(var search=new ManagementObjectSearcher("SELECT Name, DriverVersion, CurrentHorizontalResolution, CurrentVerticalResolution FROM Win32_VideoController")) foreach(ManagementObject gpu in search.Get()) Write("gpu name="+gpu["Name"]+" driver="+gpu["DriverVersion"]+" display="+gpu["CurrentHorizontalResolution"]+"x"+gpu["CurrentVerticalResolution"]); } catch(Exception e){Write("gpu.inventory.error "+e.Message);}
 }
 static void CopyTail(string source,string dest,int cap) {
   try { using(var f=new FileStream(source,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete)) {long length=f.Length,left=Math.Min((long)cap,length);f.Seek(length-left,SeekOrigin.Begin);using(var o=new FileStream(dest,FileMode.Create,FileAccess.Write,FileShare.Read)) {byte[] buffer=new byte[16384];while(left>0){int n=f.Read(buffer,0,(int)Math.Min(buffer.Length,left));if(n==0)break;o.Write(buffer,0,n);left-=n;}}} }
   catch(Exception e) { Write("log.copy.error "+Path.GetFileName(source)+" "+e.Message); }
 }
 static void CollectLogs() {
   foreach(string p in Directory.GetFiles(bin,"*.log")) CopyTail(p,Path.Combine(folder,Path.GetFileName(p)+".tail.txt"),1024*1024);
 }
 static void Modules(string label) {
   try {game.Refresh();using(var w=new StreamWriter(Path.Combine(folder,"modules-"+label+".txt"),false,Encoding.UTF8)) foreach(ProcessModule m in game.Modules) w.WriteLine("0x"+m.BaseAddress.ToInt64().ToString("x8")+" size="+m.ModuleMemorySize+" "+m.FileName+" version="+m.FileVersionInfo.FileVersion);}
   catch(Exception e){Write("module.inventory.error "+e.Message);}
 }
 static IntPtr RemoteModule(uint pid,string name) {
   IntPtr snapshot=CreateToolhelp32Snapshot(0x18,pid);if(snapshot==new IntPtr(-1))return IntPtr.Zero;
   try {MODULEENTRY m=new MODULEENTRY();m.size=(uint)Marshal.SizeOf(typeof(MODULEENTRY));if(Module32FirstW(snapshot,ref m))do {if(String.Equals(m.name,name,StringComparison.OrdinalIgnoreCase))return m.baseAddress;m.size=(uint)Marshal.SizeOf(typeof(MODULEENTRY));}while(Module32NextW(snapshot,ref m));return IntPtr.Zero;}finally{CloseHandle(snapshot);}
 }
 static uint RemoteCall(IntPtr address,IntPtr argument,out bool completed) {
   completed=false;IntPtr thread=CreateRemoteThread(processHandle,IntPtr.Zero,UIntPtr.Zero,address,argument,0,IntPtr.Zero);
   Require(thread!=IntPtr.Zero,"CreateRemoteThread");try {if(WaitForSingleObject(thread,10000)!=0){Write("hook.remote-call.timeout: allocation retained until process exit");return 0;}completed=true;uint result;Require(GetExitCodeThread(thread,out result),"GetExitCodeThread");return result;}finally{CloseHandle(thread);}
 }
 static bool Inject(uint pid,string hookPath) {
   IntPtr local=LoadLibraryExW(hookPath,IntPtr.Zero,1);Require(local!=IntPtr.Zero,"LoadLibraryEx hook image");
   try {
     IntPtr init=GetProcAddress(local,"DIAG_Initialize");Require(init!=IntPtr.Zero,"Find DIAG_Initialize");long initRva=init.ToInt64()-local.ToInt64();
     IntPtr loader=GetProcAddress(GetModuleHandleW("kernel32.dll"),"LoadLibraryW");Require(loader!=IntPtr.Zero,"Find LoadLibraryW");
     // Resolve owning module + RVA, including a forwarded KernelBase export.
     ProcessModule owner=null;using(Process self=Process.GetCurrentProcess()) foreach(ProcessModule m in self.Modules) if(loader.ToInt64()>=m.BaseAddress.ToInt64()&&loader.ToInt64()<m.BaseAddress.ToInt64()+m.ModuleMemorySize){owner=m;break;}
     if(owner==null)throw new InvalidOperationException("Cannot resolve loader module");
     IntPtr remoteOwner=IntPtr.Zero;for(int attempt=0;attempt<100;attempt++){remoteOwner=RemoteModule(pid,owner.ModuleName);if(remoteOwner!=IntPtr.Zero)break;if(Exited())break;Thread.Sleep(20);}if(remoteOwner==IntPtr.Zero)throw new InvalidOperationException("Target loader module absent; early startup failure");
     IntPtr remoteLoader=new IntPtr(remoteOwner.ToInt64()+loader.ToInt64()-owner.BaseAddress.ToInt64());
     byte[] path=Encoding.Unicode.GetBytes(hookPath+"\0");IntPtr memory=VirtualAllocEx(processHandle,IntPtr.Zero,(UIntPtr)path.Length,0x3000,4);Require(memory!=IntPtr.Zero,"VirtualAllocEx");bool loaded=false,completed=false;
     try {UIntPtr wrote;Require(WriteProcessMemory(processHandle,memory,path,(UIntPtr)path.Length,out wrote)&&wrote.ToUInt32()==path.Length,"Write hook path");uint result=RemoteCall(remoteLoader,memory,out completed);loaded=completed&&result!=0;if(!loaded){Write("hook.load.failed completed="+completed);return false;}}
     finally{if(completed)VirtualFreeEx(processHandle,memory,UIntPtr.Zero,0x8000);}
     IntPtr remote=RemoteModule(pid,Path.GetFileName(hookPath));if(remote==IntPtr.Zero){Write("hook.module.not-found");return false;}
     uint ready=RemoteCall(new IntPtr(remote.ToInt64()+initRva),IntPtr.Zero,out completed);Write("hook.initialize result="+ready+" completed="+completed);return completed&&ready==1;
   }finally{FreeLibrary(local);}
 }
 static IntPtr ExceptionCopy(uint remotePointers) {
   var pair=new byte[8];UIntPtr got;Require(ReadProcessMemory(processHandle,new IntPtr((long)remotePointers),pair,(UIntPtr)8,out got)&&got.ToUInt32()==8,"Read exception pointers");
   var record=new byte[80];var context=new byte[716];Require(ReadProcessMemory(processHandle,new IntPtr((long)BitConverter.ToUInt32(pair,0)),record,(UIntPtr)80,out got)&&got.ToUInt32()==80,"Read exception record");
   Require(ReadProcessMemory(processHandle,new IntPtr((long)BitConverter.ToUInt32(pair,4)),context,(UIntPtr)716,out got)&&got.ToUInt32()==716,"Read exception context");
   // Flatten a nested record pointer; preserve the original bytes separately.
   File.WriteAllBytes(Path.Combine(folder,"exception-record-"+dumps+".bin"),record);File.WriteAllBytes(Path.Combine(folder,"exception-context-"+dumps+".bin"),context);
   Array.Clear(record,8,4);IntPtr block=Marshal.AllocHGlobal(8+80+716);Marshal.WriteIntPtr(block,IntPtr.Add(block,8));Marshal.WriteIntPtr(block,4,IntPtr.Add(block,88));Marshal.Copy(record,0,IntPtr.Add(block,8),80);Marshal.Copy(context,0,IntPtr.Add(block,88),716);return block;
 }
 static void Snapshot(string reason,bool exception) {
   NeedReport(reason);
   if(dumps>=3){Write("snapshot.skipped limit=3 reason="+reason);return;}dumps++;
   string label=dumps.ToString("00")+"-"+reason;Write("snapshot.begin "+label);
   IntPtr pointers=IntPtr.Zero,info=IntPtr.Zero;
   try {
     if(exception){uint code=shared.ReadUInt32(16),address=shared.ReadUInt32(20),tid=shared.ReadUInt32(12);Write("exception code=0x"+code.ToString("x8")+" address=0x"+address.ToString("x8")+" thread="+tid+" flags=0x"+shared.ReadUInt32(24).ToString("x"));pointers=ExceptionCopy(shared.ReadUInt32(28));var data=new DUMP_EXCEPTION{tid=tid,pointers=pointers,clientPointers=false};info=Marshal.AllocHGlobal(Marshal.SizeOf(typeof(DUMP_EXCEPTION)));Marshal.StructureToPtr(data,info,false);}
     using(var file=new FileStream(Path.Combine(folder,label+".dmp"),FileMode.Create,FileAccess.Write,FileShare.Read)) {bool ok=MiniDumpWriteDump(processHandle,(uint)game.Id,file.SafeFileHandle.DangerousGetHandle(),DUMP_FLAGS,info,IntPtr.Zero,IntPtr.Zero);Write("snapshot.dump result="+ok+(ok?"":" "+Error("MiniDumpWriteDump")));}
   }catch(Exception e){Write("snapshot.error "+e);}
   finally{if(info!=IntPtr.Zero)Marshal.FreeHGlobal(info);if(pointers!=IntPtr.Zero)Marshal.FreeHGlobal(pointers);}
   Modules(label);CollectLogs();Write("snapshot.end "+label);
 }
 static bool ErrorOrHang(out bool hung) {
   bool anyHung=false,found=false;uint pid=(uint)game.Id;
   EnumWindows(delegate(IntPtr window,IntPtr unused){uint id;GetWindowThreadProcessId(window,out id);if(id!=pid)return true;var title=new StringBuilder(512);GetWindowTextW(window,title,title.Capacity);
     if(title.ToString().IndexOf("Internal Error",StringComparison.OrdinalIgnoreCase)>=0&&lastErrorWindow!=window.ToInt64()) {lastErrorWindow=window.ToInt64();found=true;Write("game.error-window "+title);EnumChildWindows(window,delegate(IntPtr child,IntPtr value){var text=new StringBuilder(8192);GetWindowTextW(child,text,text.Capacity);if(text.Length>0)Write("game.error-text "+text);return true;},IntPtr.Zero);}
     if(IsHungAppWindow(window))anyHung=true;return true;},IntPtr.Zero);hung=anyHung;return found;
 }
 static void NewWork() {
   folder=Path.Combine(reports,"work-"+DateTime.UtcNow.ToString("yyyyMMdd-HHmmss-fff")+"-"+Process.GetCurrentProcess().Id);
   Directory.CreateDirectory(folder);File.SetAttributes(folder,File.GetAttributes(folder)|FileAttributes.Hidden);
   File.WriteAllText(Path.Combine(folder,"diagnostics-owner.txt"),OWNER);
   using(Process self=Process.GetCurrentProcess()){File.WriteAllText(Path.Combine(folder,"monitor.pid"),self.Id.ToString());File.WriteAllText(Path.Combine(folder,"monitor-start.txt"),self.StartTime.ToUniversalTime().Ticks.ToString());}
 }
 static void NeedReport(string reason) {
   reportNeeded=true;
   try{if(folder!=null)File.WriteAllText(Path.Combine(folder,"report-requested.txt"),DateTime.UtcNow.ToString("o")+" "+reason);}catch(Exception e){Write("report.marker.error "+e.Message);}
 }
 static bool OwnWork(string dir) {
   string full=Path.GetFullPath(dir),root=Path.GetFullPath(reports).TrimEnd(Path.DirectorySeparatorChar);
   return String.Equals(Path.GetDirectoryName(full),root,StringComparison.OrdinalIgnoreCase)&&Path.GetFileName(full).StartsWith("work-",StringComparison.Ordinal)&&
     (File.GetAttributes(full)&FileAttributes.ReparsePoint)==0&&Directory.GetDirectories(full).Length==0&&
     File.Exists(Path.Combine(full,"diagnostics-owner.txt"))&&File.ReadAllText(Path.Combine(full,"diagnostics-owner.txt"))==OWNER;
 }
 static bool RecordedProcessAlive(string dir,string prefix) {
   try{string pf=Path.Combine(dir,prefix+".pid"),sf=Path.Combine(dir,prefix+"-start.txt");if(!File.Exists(pf))return false;
     int pid;long start;if(!Int32.TryParse(File.ReadAllText(pf),out pid)||!File.Exists(sf)||!Int64.TryParse(File.ReadAllText(sf),out start))return false;
     using(Process p=Process.GetProcessById(pid))return !p.HasExited&&p.StartTime.ToUniversalTime().Ticks==start;
   }catch(ArgumentException){return false;}catch(InvalidOperationException){return false;}catch{return true;}
 }
 static bool Publish(string sourceFolder) {
   string zip=Path.Combine(reports,"Brother-Report.zip"),temporary=zip+".pending-"+Guid.NewGuid().ToString("N");
   try{
     using(var output=new FileStream(temporary,FileMode.CreateNew,FileAccess.ReadWrite,FileShare.Read)){
       File.SetAttributes(temporary,File.GetAttributes(temporary)|FileAttributes.Hidden);
       using(var archive=new ZipArchive(output,ZipArchiveMode.Create,true))foreach(string source in Directory.GetFiles(sourceFolder)){
         string relative=Path.GetFileName(source);if(relative=="monitor.pid"||relative=="monitor-start.txt"||relative=="game.pid"||relative=="game-start.txt"||relative=="snapshot.request")continue;
         var entry=archive.CreateEntry(relative,CompressionLevel.Fastest);
         using(var input=new FileStream(source,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete))using(var stream=entry.Open())input.CopyTo(stream);
       }
       output.Flush(true);
     }
     File.SetAttributes(temporary,FileAttributes.Normal);
     // Never delete the last valid report before the complete replacement exists.
     if(File.Exists(zip))File.Replace(temporary,zip,null);else File.Move(temporary,zip);
     Write("archive="+zip);return true;
   }catch(Exception e){Write("archive.error "+e.Message);return false;}
   finally{try{if(File.Exists(temporary))File.Delete(temporary);}catch{}}
 }
 static void Archive() {
   if(!reportNeeded)return;
   reportPublished=false;CollectLogs();reportPublished=Publish(folder);
 }
 static void DeleteWork(string dir) {
   // Only our flat, marked, immediate child; no recursive junction traversal.
   if(!OwnWork(dir))return;
   foreach(string p in Directory.GetFiles(dir))File.Delete(p);
   Directory.Delete(dir,false);
 }
 static void FinishWork() {
   if(folder==null)return;
   try{if(Directory.Exists(folder)&&(!reportNeeded||reportPublished))DeleteWork(folder);
     if(Directory.Exists(reports)&&Directory.GetFileSystemEntries(reports).Length==0)Directory.Delete(reports,false);
   }catch{} // Keep data when it cannot safely be removed; retry on a later launch.
 }
 static void RecoverWork() {
   var dirs=new List<string>(Directory.GetDirectories(reports,"work-*"));dirs.Sort(StringComparer.Ordinal);
   foreach(string dir in dirs)try{
     if(!OwnWork(dir)||RecordedProcessAlive(dir,"monitor")||RecordedProcessAlive(dir,"game"))continue;
     string journal=Path.Combine(dir,"session.log"),text=File.Exists(journal)?File.ReadAllText(journal):"";
     bool needed=File.Exists(Path.Combine(dir,"report-requested.txt"))||!text.Contains("game.exit code=0x00000000");
     if(needed){File.AppendAllText(journal,DateTime.UtcNow.ToString("o")+" recovery.previous-monitor-ended; final process state unavailable\n");if(!Publish(dir))continue;}
     DeleteWork(dir);
   }catch(Exception e){Write("recovery.error "+e.Message);}
   // A killed publisher can leave a transaction file, never a partly replaced ZIP.
   bool active=false;foreach(string dir in Directory.GetDirectories(reports,"work-*"))try{if(OwnWork(dir)&&(RecordedProcessAlive(dir,"monitor")||RecordedProcessAlive(dir,"game")))active=true;}catch{active=true;}
   if(!active)foreach(string path in Directory.GetFiles(reports,"Brother-Report.zip.pending-*"))try{Guid id;string full=Path.GetFullPath(path);if(String.Equals(Path.GetDirectoryName(full),Path.GetFullPath(reports),StringComparison.OrdinalIgnoreCase)&&Guid.TryParseExact(Path.GetFileName(full).Substring("Brother-Report.zip.pending-".Length),"N",out id)&&(File.GetAttributes(full)&FileAttributes.ReparsePoint)==0)File.Delete(full);}catch{}
 }
 static void RequestSnapshot() {
   bool found=false;foreach(string dir in Directory.GetDirectories(reports,"work-*")){try{if(OwnWork(dir)&&RecordedProcessAlive(dir,"monitor")){File.WriteAllText(Path.Combine(dir,"snapshot.request"),DateTime.UtcNow.ToString("o"));found=true;}}catch{}}
   MessageBoxW(IntPtr.Zero,found?"Запрос диагностики отправлен. Игра останется открытой. Отчёт появится в:\n"+reports:"Активного диагностического запуска нет. Запусти игру через Start-Brother.cmd или BrotherDiagnostics.exe.","Диагностика Brother",0x40);
 }
 static int Run(string exe,string arguments,string hook) {
   string token=Guid.NewGuid().ToString("N"),name=@"Local\BrotherDiag-"+token;
   NewWork();
   using(log=new StreamWriter(Path.Combine(folder,"session.log"),false,Encoding.UTF8))
   using(var map=MemoryMappedFile.CreateNew(name,4096))
   using(shared=map.CreateViewAccessor())
   using(crash=new EventWaitHandle(false,EventResetMode.AutoReset,name+"-Crash"))
   using(done=new EventWaitHandle(false,EventResetMode.AutoReset,name+"-Done")) {
     Write("session.begin exe="+exe+" args="+arguments);shared.Write(0,MAGIC);shared.Write(4,(uint)1);
     var env=new SortedDictionary<string,string>(StringComparer.OrdinalIgnoreCase);foreach(DictionaryEntry e in Environment.GetEnvironmentVariables())env[(string)e.Key]=(string)e.Value;env["BROTHER_DIAG_TOKEN"]=token;var envText=new StringBuilder();foreach(var p in env)envText.Append(p.Key+"="+p.Value+'\0');envText.Append('\0');IntPtr environment=Marshal.StringToHGlobalUni(envText.ToString());var si=new STARTUPINFO();si.cb=(uint)Marshal.SizeOf(typeof(STARTUPINFO));PROCESS_INFORMATION pi;
     try{Require(CreateProcessW(exe,new StringBuilder("\""+exe+"\" "+arguments),IntPtr.Zero,IntPtr.Zero,false,0x404,environment,bin,ref si,out pi),"CreateProcess game");}finally{Marshal.FreeHGlobal(environment);}
     processHandle=pi.process;shared.Write(8,pi.pid);game=Process.GetProcessById((int)pi.pid);File.WriteAllText(Path.Combine(folder,"game.pid"),pi.pid.ToString());File.WriteAllText(Path.Combine(folder,"game-start.txt"),game.StartTime.ToUniversalTime().Ticks.ToString());Write("game.created pid="+pi.pid);
     try {
       // Let the Windows loader initialize before resolving remote module RVAs.
       // Early failures before the hook is ready still retain exit/startup logs.
       uint resumed=ResumeThread(pi.thread);CloseHandle(pi.thread);Write("game.resume="+resumed);if(resumed==0xffffffff)throw new InvalidOperationException("ResumeThread failed");
       try {bool ready=Inject(pi.pid,hook);Write("hook.ready="+ready);if(!ready)NeedReport("hook-unavailable");} catch(Exception e){Write("hook.unavailable "+e);NeedReport("hook-unavailable");}
       ThreadPool.QueueUserWorkItem(delegate {try{Inventory();}catch(Exception e){Write("inventory.error "+e.Message);}finally{inventoryDone.Set();}});
       DateTime heartbeat=DateTime.UtcNow,started=heartbeat,hangStart=DateTime.MinValue;bool hangDump=false;uint sequence=0;
       while(!Exited()){if(crash.WaitOne(250)){try{uint next=shared.ReadUInt32(32);if(next!=sequence){sequence=next;Snapshot("exception",true);}}finally{shared.Write(36,sequence);done.Set();}Archive();}
         if(File.Exists(Path.Combine(folder,"snapshot.request"))){File.Delete(Path.Combine(folder,"snapshot.request"));Snapshot("manual",false);Archive();}
         bool hung;try{if(ErrorOrHang(out hung)){Snapshot("error-window",false);Archive();}if(hung){if(hangStart==DateTime.MinValue)hangStart=DateTime.UtcNow;if(!hangDump&&(DateTime.UtcNow-hangStart).TotalSeconds>=30){hangDump=true;Snapshot("suspected-hang",false);Archive();}}else hangStart=DateTime.MinValue;}catch(Exception e){Write("window.status.error "+e.Message);}
         if((DateTime.UtcNow-heartbeat).TotalSeconds>=60){heartbeat=DateTime.UtcNow;Write("heartbeat elapsed="+(heartbeat-started).TotalSeconds.ToString("F0"));CollectLogs();if(reportNeeded)Archive();}
       }
       uint exitCode;Require(GetExitCodeProcess(processHandle,out exitCode),"GetExitCodeProcess");Write("game.exit code=0x"+exitCode.ToString("x8"));if(exitCode!=0)NeedReport("abnormal-exit");inventoryDone.WaitOne(2000);if(reportNeeded)Archive();return 0;
     } finally{CloseHandle(processHandle);game.Dispose();File.Delete(Path.Combine(folder,"monitor.pid"));}
   }
 }
 [STAThread] static int Main(string[] args) {
   bin=AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);fixture=args.Length>=3&&args[0]=="--test-target";reports=ReportRoot(bin);
   try {
     if(args.Length>0&&args[0]=="--snapshot"){RequestSnapshot();return 0;}
     if(args.Length>0&&args[0]=="--reports"){Process.Start(reports);return 0;}
     string exe=Path.Combine(bin,"brother.exe"),arguments="2brother.main_db",hook=Path.Combine(bin,"BrotherCrashHook.dll");
     if(fixture){exe=Path.GetFullPath(args[1]);arguments=args[2];bin=Path.GetDirectoryName(exe);hook=Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"BrotherCrashHook.dll");reports=Path.Combine(bin,"Reports");Directory.CreateDirectory(reports);}
     if(!File.Exists(exe)||!File.Exists(hook))throw new FileNotFoundException("Для запуска нужны brother.exe и BrotherCrashHook.dll рядом с BrotherDiagnostics.exe.");
     if(!fixture&&Process.GetProcessesByName("brother").Length!=0)throw new InvalidOperationException("Игра уже запущена. Сохрани прогресс и закрой её перед новым диагностическим запуском.");
     RecoverWork();return Run(exe,arguments,hook);
   }catch(Exception e){try{if(log!=null)Write("monitor.error "+e);}catch{}try{if(folder==null)NewWork();NeedReport("startup-error");File.AppendAllText(Path.Combine(folder,"startup-error.txt"),DateTime.UtcNow.ToString("o")+"\nOS="+Environment.OSVersion+"\n"+e);Archive();}catch{}if(!fixture)MessageBoxW(IntPtr.Zero,"Не удалось запустить диагностику:\n"+e.Message+"\n\nОтчёт: "+Path.Combine(reports,"Brother-Report.zip"),"Диагностика Brother",0x10);return 1;}
   finally{FinishWork();}
 }
}
