using System;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using System.Text;
[ComImport,Guid("00021401-0000-0000-C000-000000000046")]class TestShellLink {}
[ComImport,Guid("000214F9-0000-0000-C000-000000000046"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface ITestShellLinkW {
 void GetPath([Out,MarshalAs(UnmanagedType.LPWStr)]StringBuilder path,int length,IntPtr data,uint flags);
 void GetIDList(out IntPtr list);void SetIDList(IntPtr list);
 void GetDescription([Out,MarshalAs(UnmanagedType.LPWStr)]StringBuilder text,int length);
 void SetDescription([MarshalAs(UnmanagedType.LPWStr)]string text);
 void GetWorkingDirectory([Out,MarshalAs(UnmanagedType.LPWStr)]StringBuilder path,int length);
 void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)]string path);
 void GetArguments([Out,MarshalAs(UnmanagedType.LPWStr)]StringBuilder args,int length);
}
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
  object link=null;try{link=new TestShellLink();((System.Runtime.InteropServices.ComTypes.IPersistFile)link).Load(first,0);var sl=(ITestShellLinkW)link;var target=new StringBuilder(32768);var cwd=new StringBuilder(32768);var arguments=new StringBuilder(32768);sl.GetPath(target,target.Capacity,IntPtr.Zero,4);sl.GetWorkingDirectory(cwd,cwd.Capacity);sl.GetArguments(arguments,arguments.Capacity);
   Console.WriteLine("TargetPath="+target);Console.WriteLine("WorkingDirectory="+cwd);Console.WriteLine("Arguments="+arguments);
   if(!String.Equals(target.ToString(),Path.Combine(root,"Bin","BrotherDiagnostics.exe"),StringComparison.OrdinalIgnoreCase))throw new Exception("Wrong shortcut target.");
   if(!String.Equals(cwd.ToString(),Path.Combine(root,"Bin"),StringComparison.OrdinalIgnoreCase))throw new Exception("Wrong shortcut working directory.");
   if(arguments.Length!=0)throw new Exception("Wrong shortcut arguments.");
  }finally{if(link!=null&&Marshal.IsComObject(link))Marshal.FinalReleaseComObject(link);}
  Console.WriteLine("UI preview and isolated shortcut checks passed.");return 0;
 }catch(Exception e){Console.Error.WriteLine(e);return 1;}}
}
