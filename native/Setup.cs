using System;
using System.IO;
using System.IO.Compression;
using System.Diagnostics;
using System.Windows.Forms;
using System.Threading;

class Setup {
    static string LogPath() {
        return Path.Combine(Path.GetTempPath(), "ReformPinyin-setup.log");
    }
    static string LogPath(string[] args) {
        for (int i=0; i+1<args.Length; i++)
            if (args[i] == "--log") return args[i+1];
        return LogPath();
    }
    static string ReadLog(string path) {
        try { return File.Exists(path) ? File.ReadAllText(path) : ""; }
        catch { return ""; }
    }
    static void WriteFailure(string path, Exception error) {
        string detail = error.ToString();
        if (File.Exists(path)) {
            string existing = ReadLog(path);
            if (existing.IndexOf(detail, StringComparison.Ordinal) >= 0) return;
            File.AppendAllText(path, Environment.NewLine + Environment.NewLine +
                "外层安装器：" + detail);
            return;
        }
        File.WriteAllText(path, detail);
    }
    [STAThread] static int Main(string[] args) {
        bool quiet = Array.IndexOf(args, "--quiet") >= 0;
        string logPath = LogPath(args);
        string stage = "准备安装";
        if (Array.IndexOf(args, "--register") < 0) {
            try { if (File.Exists(logPath)) File.Delete(logPath); }
            catch { }
        }
        try {
            string parent = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "ReformPinyin");
            string root = Path.Combine(parent, "app-0.2.4");
            if (Array.IndexOf(args, "--register") < 0) {
                stage = "请求管理员权限";
                string cleanLogPath = logPath.Replace(new string((char)34, 1), "");
                var elevate = new ProcessStartInfo(Application.ExecutablePath,
                    "--register --quiet --log " + new string((char)34, 1) + cleanLogPath + new string((char)34, 1)) {UseShellExecute=true,Verb="runas"};
                using(var installer=Process.Start(elevate)) {
                    installer.WaitForExit();
                    if(installer.ExitCode!=0) {
                        string detail = ReadLog(logPath);
                        throw new Exception("Windows 注册失败，提权安装程序退出码 " + installer.ExitCode +
                            "。" + Environment.NewLine + detail + Environment.NewLine +
                            "完整日志：" + logPath);
                    }
                }
                Process.Start(new ProcessStartInfo(Path.Combine(root,"ReformHost.exe")){UseShellExecute=false,CreateNoWindow=true});
                if(!quiet)MessageBox.Show("按 Win + 空格选择「改革拼音」，单按 Shift 切换中英。可从开始菜单打开「改革拼音控制面板」。","改革拼音");
                return 0;
            }
            stage = "解包安装文件";
            string archive = Path.GetTempFileName();
            try {
                using (var file=File.OpenRead(Application.ExecutablePath))
                using (var output=File.Create(archive)) {
                    file.Seek(-8,SeekOrigin.End);
                    long size=new BinaryReader(file).ReadInt64();
                    if(size<=0 || size>file.Length-8) throw new InvalidDataException("安装包损坏");
                    file.Seek(-size-8,SeekOrigin.End);
                    byte[] buffer=new byte[131072];
                    while(size>0) {
                        int count=file.Read(buffer,0,(int)Math.Min(size,buffer.Length));
                        if(count<=0)throw new EndOfStreamException();
                        output.Write(buffer,0,count);
                        size-=count;
                    }
                }
                Directory.CreateDirectory(root);
                using(var zip=ZipFile.OpenRead(archive)) foreach(var entry in zip.Entries) {
                    string path=Path.GetFullPath(Path.Combine(root,entry.FullName));
                    if(!path.StartsWith(root+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))throw new InvalidDataException();
                    Directory.CreateDirectory(Path.GetDirectoryName(path));
                    if(entry.Name.Length>0)entry.ExtractToFile(path,true);
                }
            } finally { File.Delete(archive); }
            stage = "注册 Windows 输入法";
            var info=new ProcessStartInfo("powershell.exe","-NoProfile -ExecutionPolicy Bypass -File \""+Path.Combine(root,"Install.ps1")+"\""){
                 UseShellExecute=false,CreateNoWindow=true,RedirectStandardError=true};
            using(var p=Process.Start(info)) {
                string error=p.StandardError.ReadToEnd();p.WaitForExit();
                if(p.ExitCode!=0)throw new Exception("Install.ps1 退出码 " + p.ExitCode +
                    Environment.NewLine + error);
            }
            return 0;
        } catch(Exception e) {
            Exception detailed = new Exception("失败阶段：" + stage, e);
            WriteFailure(logPath,detailed);
            if(!quiet)MessageBox.Show(detailed.ToString() + Environment.NewLine +
                Environment.NewLine + "日志：" + logPath,"改革拼音安装");
            return 1;
        }
    }
}
