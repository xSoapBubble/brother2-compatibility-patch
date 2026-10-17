using System;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Windows.Forms;
class InstallerHarness {
 [STAThread]static int Main(string[] args){try{
  var assembly=Assembly.LoadFrom(args[0]);
  Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
  using(var f=(Form)Activator.CreateInstance(assembly.GetType("PatchForm"))){
   f.StartPosition=FormStartPosition.Manual;f.Location=new Point(-30000,-30000);f.ShowInTaskbar=false;f.Show();f.PerformLayout();Application.DoEvents();
   using(var b=new Bitmap(f.Width,f.Height)){f.DrawToBitmap(b,new Rectangle(0,0,b.Width,b.Height));b.Save(args[1]);}f.Hide();
  }
  string desktop=args[2],root=args[3];Directory.CreateDirectory(desktop);
  string foreign=Path.Combine(desktop,"Брат 2 — исправленная версия.lnk");File.WriteAllText(foreign,"existing user shortcut sentinel");
  var m=assembly.GetType("PatchEngine").GetMethod("MakeShortcutIn",BindingFlags.NonPublic|BindingFlags.Static);
  string first=(string)m.Invoke(null,new object[]{root,desktop});DateTime time=File.GetLastWriteTimeUtc(first);
  string second=(string)m.Invoke(null,new object[]{root,desktop});
  if(first!=second||time!=File.GetLastWriteTimeUtc(second)||Directory.GetFiles(desktop).Length!=2||File.ReadAllText(foreign)!="existing user shortcut sentinel")throw new Exception("Shortcut is not idempotent or replaced a user file.");
  object shell=null,link=null;try{var t=Type.GetTypeFromProgID("WScript.Shell",true);shell=Activator.CreateInstance(t);link=t.InvokeMember("CreateShortcut",BindingFlags.InvokeMethod,null,shell,new object[]{first});
   foreach(var name in new[]{"TargetPath","WorkingDirectory","Arguments","IconLocation"})Console.WriteLine(name+"="+link.GetType().InvokeMember(name,BindingFlags.GetProperty,null,link,null));
   if(!String.Equals(Convert.ToString(link.GetType().InvokeMember("TargetPath",BindingFlags.GetProperty,null,link,null)),Path.Combine(root,"Bin","BrotherDiagnostics.exe"),StringComparison.OrdinalIgnoreCase))throw new Exception("Wrong shortcut target.");
   if(!String.Equals(Convert.ToString(link.GetType().InvokeMember("WorkingDirectory",BindingFlags.GetProperty,null,link,null)),Path.Combine(root,"Bin"),StringComparison.OrdinalIgnoreCase))throw new Exception("Wrong shortcut working directory.");
   if(Convert.ToString(link.GetType().InvokeMember("Arguments",BindingFlags.GetProperty,null,link,null))!="")throw new Exception("Wrong shortcut arguments.");
  }finally{if(link!=null&&Marshal.IsComObject(link))Marshal.FinalReleaseComObject(link);if(shell!=null&&Marshal.IsComObject(shell))Marshal.FinalReleaseComObject(shell);}
  Console.WriteLine("UI preview and isolated shortcut checks passed.");return 0;
 }catch(Exception e){Console.Error.WriteLine(e);return 1;}}
}
