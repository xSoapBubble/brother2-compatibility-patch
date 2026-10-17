using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

[ComImport,Guid("00021401-0000-0000-C000-000000000046")]
class UnicodeShellLink {}
[ComImport,Guid("000214F9-0000-0000-C000-000000000046"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IShellLinkW {
 void GetPath([Out,MarshalAs(UnmanagedType.LPWStr)]StringBuilder path,int length,IntPtr findData,uint flags);
 void GetIDList(out IntPtr list);void SetIDList(IntPtr list);
 void GetDescription([Out,MarshalAs(UnmanagedType.LPWStr)]StringBuilder text,int length);
 void SetDescription([MarshalAs(UnmanagedType.LPWStr)]string text);
 void GetWorkingDirectory([Out,MarshalAs(UnmanagedType.LPWStr)]StringBuilder path,int length);
 void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)]string path);
 void GetArguments([Out,MarshalAs(UnmanagedType.LPWStr)]StringBuilder args,int length);
 void SetArguments([MarshalAs(UnmanagedType.LPWStr)]string args);
 void GetHotkey(out short key);void SetHotkey(short key);void GetShowCmd(out int command);void SetShowCmd(int command);
 void GetIconLocation([Out,MarshalAs(UnmanagedType.LPWStr)]StringBuilder path,int length,out int index);
 void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)]string path,int index);
 void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)]string path,uint reserved);
 void Resolve(IntPtr window,uint flags);void SetPath([MarshalAs(UnmanagedType.LPWStr)]string path);
}

// Installer uses only the selected game directory. No registry changes/backups.
public class PatchBase { public string Sha256,Blob;public int Size; }
public class PatchEntry {
 public string Path,Mode,Blob,BaseSha256,Sha256; public int BaseSize,Size;
 public List<PatchBase> Updates;
 public List<PatchBase> KnownVersions;
}
public class Anchor { public string Path,Sha256; public int Size; }
public class PatchManifest {
 public string Id,Version;public List<PatchEntry> Files;public List<Anchor> Requires;public List<string> Directories;
}
public class PatchResult { public string Status,Root,Version,Shortcut,Note;public int Changed; }
class ValidationError:Exception {public ValidationError(string s):base(s){}}
class Payload {
 public PatchManifest Manifest;public Dictionary<string,byte[]> Blobs=new Dictionary<string,byte[]>(StringComparer.Ordinal);
 public static string Hash(byte[] b){using(var s=SHA256.Create())return BitConverter.ToString(s.ComputeHash(b)).Replace("-","").ToLowerInvariant();}
 public static Payload Load(){
  byte[] bytes;using(var s=Assembly.GetExecutingAssembly().GetManifestResourceStream("BrotherPatch.Payload")){if(s==null)throw new InvalidDataException("В установщике отсутствуют данные патча.");using(var m=new MemoryStream()){s.CopyTo(m);bytes=m.ToArray();}}
  if(Hash(bytes)!=BuildIdentity.PayloadSha256)throw new InvalidDataException("Установщик повреждён. Заново распакуйте архив патча.");
  var p=new Payload();using(var ms=new MemoryStream(bytes))using(var zip=new ZipArchive(ms,ZipArchiveMode.Read)){
   using(var r=new StreamReader(zip.GetEntry("manifest.json").Open(),Encoding.UTF8))p.Manifest=new JavaScriptSerializer().Deserialize<PatchManifest>(r.ReadToEnd());
   if(p.Manifest.Id!="brother-compatibility"||p.Manifest.Version!=BuildIdentity.Version)throw new InvalidDataException("Неверный формат патча.");
   var paths=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
   foreach(var e in p.Manifest.Files){if(!paths.Add(e.Path)||e.Size<0||e.Size>64*1024*1024)throw new InvalidDataException("Неверный список файлов.");
    var names=new List<string>{e.Blob};if(e.Updates!=null)foreach(var u in e.Updates)names.Add(u.Blob);
    foreach(string name in names){var z=zip.GetEntry(name);if(z==null||z.Length>64*1024*1024)throw new InvalidDataException("Отсутствует часть патча.");
     using(var s=z.Open())using(var m=new MemoryStream()){s.CopyTo(m);p.Blobs.Add(name,m.ToArray());}
    }
   }
  }return p;
 }
}
class PlannedFile {
 public PatchEntry Entry;public string Target,Stage;public byte[] Before,After;public FileAttributes Attributes;public DateTime Time;
}
class PatchEngine {
 [DllImport("kernel32.dll",SetLastError=true)]static extern IntPtr OpenProcess(uint access,bool inherit,int pid);
 [DllImport("kernel32.dll",SetLastError=true,CharSet=CharSet.Unicode)]static extern bool QueryFullProcessImageName(IntPtr process,uint flags,StringBuilder path,ref int size);
 [DllImport("kernel32.dll")]static extern bool CloseHandle(IntPtr handle);
 readonly Payload payload;
 public PatchEngine(Payload p){payload=p;}
 public static string Root(string chosen){
  if(String.IsNullOrWhiteSpace(chosen))throw new ValidationError("Выберите папку игры.");
  string root=System.IO.Path.GetFullPath(chosen.Trim().Trim('"'));
  if(!Directory.Exists(root))throw new ValidationError("Папка не найдена.");
  if(File.Exists(System.IO.Path.Combine(root,"Bin","brother.exe")))return root.TrimEnd(System.IO.Path.DirectorySeparatorChar);
  if(String.Equals(new DirectoryInfo(root).Name,"Bin",StringComparison.OrdinalIgnoreCase)&&File.Exists(System.IO.Path.Combine(root,"brother.exe")))return Directory.GetParent(root).FullName;
  throw new ValidationError("Выберите папку игры Brother или Bin, содержащую brother.exe.");
 }
 static string Target(string root,string relative){
  if(String.IsNullOrEmpty(relative)||System.IO.Path.IsPathRooted(relative)||relative.Contains(":")||relative.Contains(".."))throw new InvalidDataException("Небезопасный путь в пакете.");
  string result=System.IO.Path.GetFullPath(System.IO.Path.Combine(root,relative.Replace('/',System.IO.Path.DirectorySeparatorChar)));
  if(!result.StartsWith(root.TrimEnd(System.IO.Path.DirectorySeparatorChar)+System.IO.Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))throw new InvalidDataException("Путь вышел за пределы игры.");
  string part=result;while(part!=null&&part.Length>=root.Length){if((File.Exists(part)||Directory.Exists(part))&&(File.GetAttributes(part)&FileAttributes.ReparsePoint)!=0)throw new ValidationError("Папка игры содержит перенаправления файлов. Выберите обычную папку с игрой.");if(String.Equals(part,root,StringComparison.OrdinalIgnoreCase))break;part=System.IO.Path.GetDirectoryName(part);}
  return result;
 }
 static string ProcessImage(int pid){
  IntPtr handle=OpenProcess(0x1000,false,pid);if(handle==IntPtr.Zero)throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
  try{var path=new StringBuilder(32768);int size=path.Capacity;if(!QueryFullProcessImageName(handle,0,path,ref size))throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());return path.ToString();}finally{CloseHandle(handle);}
 }
 static void Closed(string root){
  foreach(string name in new[]{"brother","BrotherDiagnostics"})foreach(Process p in Process.GetProcessesByName(name))using(p){
   try{string path=ProcessImage(p.Id);if(String.Equals(System.IO.Path.GetFullPath(path),System.IO.Path.Combine(root,"Bin",name+".exe"),StringComparison.OrdinalIgnoreCase))throw new ValidationError("Закройте игру и дождитесь завершения диагностики, затем повторите установку.");}
   catch(ValidationError){throw;}catch(System.ComponentModel.Win32Exception e){if(e.NativeErrorCode!=87&&e.NativeErrorCode!=1168)throw new ValidationError("Закройте запущенную игру, затем повторите установку.");}catch(InvalidOperationException){}
  }
 }
 static byte[] Delta(byte[] original,byte[] patch,PatchEntry e){
  using(var m=new MemoryStream(patch))using(var r=new BinaryReader(m)){
   if(Encoding.ASCII.GetString(r.ReadBytes(8))!="B2PATCH1")throw new InvalidDataException("Неверный бинарный патч.");
   int size=r.ReadInt32(),count=r.ReadInt32();if(size!=e.Size||count<0||count>100000)throw new InvalidDataException("Неверная длина патча.");
   var output=new byte[size];Buffer.BlockCopy(original,0,output,0,Math.Min(original.Length,size));int end=0;
   for(int i=0;i<count;i++){int start=r.ReadInt32(),n=r.ReadInt32();if(start<end||n<=0||start<0||start>size||n>size-start)throw new InvalidDataException("Повреждённый диапазон патча.");var b=r.ReadBytes(n);if(b.Length!=n)throw new InvalidDataException("Патч обрезан.");Buffer.BlockCopy(b,0,output,start,n);end=start+n;}
   if(m.Position!=m.Length)throw new InvalidDataException("Лишние данные патча.");return output;
  }
 }
 List<PlannedFile> Plan(string root,bool verify){
  Closed(root);
  foreach(var a in payload.Manifest.Requires){string p=Target(root,a.Path);if(!File.Exists(p)||new FileInfo(p).Length!=a.Size||Payload.Hash(File.ReadAllBytes(p))!=a.Sha256)throw new ValidationError("Версия игры не подходит: "+a.Path+" отличается от проверенного оригинала. Файлы не изменены.");}
  foreach(string name in payload.Manifest.Directories){string p=Target(root,name);if(!Directory.Exists(p)||Directory.GetFiles(p,"*",SearchOption.AllDirectories).Length==0)throw new ValidationError("Не найдены игровые ресурсы: "+name+". Нужна полная установленная игра.");}
  var plan=new List<PlannedFile>();foreach(var e in payload.Manifest.Files){string p=Target(root,e.Path);byte[] before=File.Exists(p)?File.ReadAllBytes(p):null;string hash=before==null?null:Payload.Hash(before);
   if(hash==e.Sha256&&before.Length==e.Size)continue;
   if(verify)throw new ValidationError("Файл не соответствует установленному патчу: "+e.Path);
   byte[] after;
   PatchBase update=null;if(before!=null&&e.Updates!=null)foreach(var u in e.Updates)if(hash==u.Sha256&&before.Length==u.Size){update=u;break;}
   if(update!=null)after=Delta(before,payload.Blobs[update.Blob],e);
   else if(e.Mode=="delta"){
    if(before==null||hash!=e.BaseSha256||before.Length!=e.BaseSize)throw new ValidationError("Версия игры не подходит: "+e.Path+" уже изменён или относится к другому изданию. Файлы не изменены.");
    after=Delta(before,payload.Blobs[e.Blob],e);
   }else if(e.Mode=="copy"){
    bool known=false;if(before!=null&&e.KnownVersions!=null)foreach(var v in e.KnownVersions)if(hash==v.Sha256&&before.Length==v.Size){known=true;break;}
    if(before!=null&&!known)throw new ValidationError("Файл "+e.Path+" уже существует и отличается от версии патча. Файлы не изменены.");
    after=payload.Blobs[e.Blob];
   }else throw new InvalidDataException("Неизвестный тип патча.");
   if(after.Length!=e.Size||Payload.Hash(after)!=e.Sha256)throw new InvalidDataException("Ошибка проверки подготовленного файла: "+e.Path);
   plan.Add(new PlannedFile{Entry=e,Target=p,Before=before,After=after,Attributes=before==null?FileAttributes.Normal:File.GetAttributes(p),Time=before==null?DateTime.MinValue:File.GetLastWriteTimeUtc(p)});
  }return plan;
 }
 public PatchResult Check(string chosen,bool verify){string root=Root(chosen);var p=Plan(root,verify);return new PatchResult{Status=verify?"verified":p.Count==0?"already-installed":"compatible",Root=root,Changed=p.Count,Version=payload.Manifest.Version};}
 static void Replace(string source,string target){if(File.Exists(target))File.Replace(source,target,null);else File.Move(source,target);}
 static void CleanStage(string root,string dir,List<string> owned){
  if(dir==null||!Directory.Exists(dir))return;
  if(!String.Equals(System.IO.Path.GetDirectoryName(System.IO.Path.GetFullPath(dir)),root,StringComparison.OrdinalIgnoreCase)||!System.IO.Path.GetFileName(dir).StartsWith(".BrotherPatch-temp-",StringComparison.Ordinal)||(File.GetAttributes(dir)&FileAttributes.ReparsePoint)!=0)return;
  foreach(string path in owned)if(File.Exists(path)&&String.Equals(System.IO.Path.GetDirectoryName(path),dir,StringComparison.OrdinalIgnoreCase))File.Delete(path);
  if(Directory.GetFileSystemEntries(dir).Length==0)Directory.Delete(dir,false);
 }
 public PatchResult Install(string chosen,bool shortcut,Action<string> progress){
  string root=Root(chosen);if(progress!=null)progress("Проверяю версию игры и данные патча…");var plan=Plan(root,false);
  string stage=null;var owned=new List<string>();var changed=new List<PlannedFile>();
  try{
   if(plan.Count>0){
    stage=System.IO.Path.Combine(root,".BrotherPatch-temp-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(stage);File.SetAttributes(stage,File.GetAttributes(stage)|FileAttributes.Hidden);
    for(int i=0;i<plan.Count;i++){var f=plan[i];f.Stage=System.IO.Path.Combine(stage,i.ToString("0000")+".tmp");owned.Add(f.Stage);using(var s=new FileStream(f.Stage,FileMode.CreateNew,FileAccess.Write,FileShare.None)){s.Write(f.After,0,f.After.Length);s.Flush(true);}if(Payload.Hash(File.ReadAllBytes(f.Stage))!=f.Entry.Sha256)throw new IOException("Не удалось проверить записанный файл.");}
    Closed(root);if(progress!=null)progress("Устанавливаю исправления…");
    foreach(var f in plan){Target(root,f.Entry.Path);byte[] now=File.Exists(f.Target)?File.ReadAllBytes(f.Target):null;if((now==null)!=(f.Before==null)||(now!=null&&Payload.Hash(now)!=Payload.Hash(f.Before)))throw new IOException("Файл изменился во время установки: "+f.Entry.Path);
     Replace(f.Stage,f.Target);changed.Add(f);
    }
   }
  }catch(Exception original){
   // Undo an ordinary failed transaction from memory only; no old files are saved.
   string failed="";for(int i=changed.Count-1;i>=0;i--)try{var f=changed[i];Target(root,f.Entry.Path);if(!File.Exists(f.Target)||Payload.Hash(File.ReadAllBytes(f.Target))!=f.Entry.Sha256){failed+=f.Entry.Path+" ";continue;}
    if(f.Before==null)File.Delete(f.Target);else{string p=System.IO.Path.Combine(stage,"memory-"+i+".tmp");File.WriteAllBytes(p,f.Before);owned.Add(p);Replace(p,f.Target);File.SetLastWriteTimeUtc(f.Target,f.Time);File.SetAttributes(f.Target,f.Attributes);}
   }catch{failed+=changed[i].Entry.Path+" ";}
   if(failed.Length>0)throw new IOException("Установка прервана. Повторите установку после устранения причины. Не удалось вернуть файлы: "+failed,original);throw;
  }finally{try{CleanStage(root,stage,owned);}catch{}}
  var result=new PatchResult{Status=plan.Count==0?"already-installed":"installed",Root=root,Changed=plan.Count,Version=payload.Manifest.Version};
  if(shortcut)AddShortcut(result);
  return result;
 }
 public void AddShortcut(PatchResult result){try{result.Shortcut=MakeShortcut(result.Root);}catch(Exception e){result.Note="Ярлык создать не удалось: "+e.Message+". Запускайте Start-Brother.cmd в папке игры.";}}
 static string MakeShortcut(string root){
  string desktop=Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);if(String.IsNullOrEmpty(desktop))throw new IOException("Рабочий стол недоступен.");
  return MakeShortcutIn(root,desktop);
 }
 static string MakeShortcutIn(string root,string desktop){
  string stem="Брат 2 — исправленная версия",path=null;
  object link=null;try{
   for(int i=1;i<100;i++){string p=System.IO.Path.Combine(desktop,stem+(i==1?"":" ("+i+")")+".lnk");if(!File.Exists(p)){if(path==null)path=p;continue;}
    object existing=null;try{existing=new UnicodeShellLink();((System.Runtime.InteropServices.ComTypes.IPersistFile)existing).Load(p,0);var sl=(IShellLinkW)existing;var target=new StringBuilder(32768);var cwd=new StringBuilder(32768);var args=new StringBuilder(32768);sl.GetPath(target,target.Capacity,IntPtr.Zero,4);sl.GetWorkingDirectory(cwd,cwd.Capacity);sl.GetArguments(args,args.Capacity);
     if(String.Equals(target.ToString(),System.IO.Path.Combine(root,"Bin","BrotherDiagnostics.exe"),StringComparison.OrdinalIgnoreCase)&&String.Equals(cwd.ToString(),System.IO.Path.Combine(root,"Bin"),StringComparison.OrdinalIgnoreCase)&&args.Length==0)return p;
    }catch{}finally{if(existing!=null&&Marshal.IsComObject(existing))Marshal.FinalReleaseComObject(existing);}
   }
   if(path==null)throw new IOException("Не найдено свободное имя ярлыка.");
   link=new UnicodeShellLink();var created=(IShellLinkW)link;
   created.SetPath(System.IO.Path.Combine(root,"Bin","BrotherDiagnostics.exe"));created.SetWorkingDirectory(System.IO.Path.Combine(root,"Bin"));created.SetArguments("");created.SetIconLocation(System.IO.Path.Combine(root,"Bin","brother.exe"),0);created.SetDescription("Брат 2: Обратно в Америку — исправленная версия");
   ((System.Runtime.InteropServices.ComTypes.IPersistFile)link).Save(path,true);return path;
  }finally{if(link!=null&&Marshal.IsComObject(link))Marshal.FinalReleaseComObject(link);}
 }
}
public class PatchForm:Form {
 readonly TextBox folder=new TextBox(),status=new TextBox();readonly Button browse=new Button(),install=new Button();readonly CheckBox shortcut=new CheckBox();readonly PatchEngine engine;bool busy;
 public PatchForm(){engine=new PatchEngine(Payload.Load());Text="Брат 2 — патч совместимости "+BuildIdentity.Version;ClientSize=new Size(720,366);MinimumSize=new Size(736,405);StartPosition=FormStartPosition.CenterScreen;Font=new Font("Segoe UI",10);AutoScaleMode=AutoScaleMode.Font;
  var title=new Label{Text="Брат 2: Обратно в Америку",Font=new Font("Segoe UI",17,FontStyle.Bold),Bounds=new Rectangle(24,20,670,36),AutoSize=false};Controls.Add(title);
  Controls.Add(new Label{Text="Патч совместимости "+BuildIdentity.Version+" · Windows 10 / 11",Bounds=new Rectangle(26,60,660,24)});
  Controls.Add(new Label{Text="Выберите папку игры Brother.",Bounds=new Rectangle(26,106,660,24)});
  folder.SetBounds(26,136,550,28);folder.Anchor=AnchorStyles.Top|AnchorStyles.Left|AnchorStyles.Right;Controls.Add(folder);
  browse.Text="Выбрать…";browse.SetBounds(588,134,106,32);browse.Anchor=AnchorStyles.Top|AnchorStyles.Right;browse.Click+=delegate{using(var d=new FolderBrowserDialog{Description="Выберите папку игры Brother.",ShowNewFolderButton=false}){if(Directory.Exists(folder.Text))d.SelectedPath=folder.Text;if(d.ShowDialog(this)==DialogResult.OK)folder.Text=d.SelectedPath;}};Controls.Add(browse);
  shortcut.Text="Создать ярлык на рабочем столе";shortcut.Checked=true;shortcut.SetBounds(26,184,650,28);Controls.Add(shortcut);
  status.Multiline=true;status.ReadOnly=true;status.BorderStyle=BorderStyle.None;status.BackColor=SystemColors.Control;status.SetBounds(26,225,668,68);status.Anchor=AnchorStyles.Top|AnchorStyles.Left|AnchorStyles.Right;Controls.Add(status);
  install.Text="Установить";install.SetBounds(544,310,150,36);install.Anchor=AnchorStyles.Bottom|AnchorStyles.Right;install.Click+=async delegate{if(busy)return;busy=true;install.Enabled=browse.Enabled=folder.Enabled=shortcut.Enabled=false;string chosen=folder.Text;bool create=shortcut.Checked;
   try{PatchResult r=await Task.Run(()=>engine.Install(chosen,false,s=>{if(IsHandleCreated)BeginInvoke((Action)(()=>status.Text=s));}));
    // WScript shortcut is created on the STA UI thread.
    if(create)engine.AddShortcut(r);
    status.Text=(r.Status=="already-installed"?"Эта версия патча уже установлена.":"Патч установлен.")+"\r\n"+(r.Note??(r.Shortcut!=null?"Запускайте игру с нового ярлыка.":"Запускайте Start-Brother.cmd в папке игры."));
   }catch(Exception e){status.Text=e is UnauthorizedAccessException?"Нет прав записи в папку игры. Запустите установщик от имени администратора.":e.Message;MessageBox.Show(this,status.Text,"Патч не установлен",MessageBoxButtons.OK,MessageBoxIcon.Warning);}
   finally{busy=false;install.Enabled=browse.Enabled=folder.Enabled=shortcut.Enabled=true;}
  };Controls.Add(install);
  FormClosing+=delegate(object s,FormClosingEventArgs e){if(busy){e.Cancel=true;status.Text="Дождитесь окончания установки.";}};
 }
}
static class Program {
 [DllImport("kernel32")]static extern bool AttachConsole(uint pid);
 [STAThread]static int Main(string[] args){
  if(args.Length>0){try{AttachConsole(0xffffffff);Console.OutputEncoding=new UTF8Encoding(false);if((args.Length!=2&&args.Length!=3)||(args.Length==3&&(args[0]!="--install"||args[2]!="--shortcut")))throw new ArgumentException("Использование: BrotherPatch.exe --check|--install|--verify \"папка игры\" [--shortcut]");
    var engine=new PatchEngine(Payload.Load());PatchResult r;
    if(args[0]=="--install")r=engine.Install(args[1],args.Length==3&&args[2]=="--shortcut",null);
    else if(args[0]=="--check")r=engine.Check(args[1],false);else if(args[0]=="--verify")r=engine.Check(args[1],true);else throw new ArgumentException("Неизвестная команда.");
    Console.WriteLine(new JavaScriptSerializer().Serialize(r));return 0;
   }catch(Exception e){Console.Error.WriteLine(e.Message);return e is ValidationError?2:1;}
  }
  try{Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);Application.Run(new PatchForm());return 0;}
  catch(Exception e){MessageBox.Show(e.Message,"Не удалось открыть установщик",MessageBoxButtons.OK,MessageBoxIcon.Error);return 1;}
 }
}
