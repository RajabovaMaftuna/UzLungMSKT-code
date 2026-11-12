// UzLungMSKT o'rnatuvchisi v2: exe yonidagi UzLungMSKT_parts.json va UzLungMSKT_data_NN.zip qismlarini tekshiradi (hajm + sha256), ochadi,
// har faylni hajm bo'yicha tekshiradi (xato bo'lsa bir marta qayta urinadi), workspace dagi foydalanuvchi ma'lumotlarini saqlaydi,
// avtostart va yorliq yaratadi, serverni ishga tushiradi. Parametrlar: --dir --port --no-autostart --no-shortcut --no-browser --quiet --skip-verify
using System; using System.Collections.Generic; using System.Diagnostics; using System.IO; using System.IO.Compression; using System.Linq;
using System.Security.Cryptography; using System.Text; using System.Text.RegularExpressions;

class Program {
    static string LogPath;
    static void Log(string s) { Console.WriteLine(s); try { File.AppendAllText(LogPath, DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "  " + s + Environment.NewLine, Encoding.UTF8); } catch { } }
    static string Arg(string[] a, string k, string d) { int i = Array.IndexOf(a, k); return (i >= 0 && i + 1 < a.Length) ? a[i + 1] : d; }
    static void MakeLnk(string path, string target, string args, string cwd, string what) {
        try {
            dynamic sh = Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
            dynamic lnk = sh.CreateShortcut(path);
            lnk.TargetPath = target; lnk.Arguments = args; lnk.WorkingDirectory = cwd; lnk.Description = "UzLungMSKT"; lnk.Save();
            Log(what + " yaratildi: " + path);
        } catch (Exception ex) { Log(what + " yaratilmadi: " + ex.Message); }
    }
    static int Run(string exe, string args, string cwd, int waitMs) {
        var p = new ProcessStartInfo(exe, args) { WorkingDirectory = cwd, UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true };
        p.EnvironmentVariables.Remove("PYTHONPATH"); p.EnvironmentVariables.Remove("PYTHONHOME");
        using (var pr = Process.Start(p)) { string o = pr.StandardOutput.ReadToEnd() + pr.StandardError.ReadToEnd(); if (!pr.WaitForExit(waitMs)) return -1; if (o.Trim().Length > 0) Log("  " + o.Trim()); return pr.ExitCode; }
    }
    static string Sha(string f) { using (var s = File.OpenRead(f)) using (var h = SHA256.Create()) return BitConverter.ToString(h.ComputeHash(s)).Replace("-", "").ToLowerInvariant(); }
    static void Extract(ZipArchiveEntry e, string dst) {
        for (int k = 0; k < 2; k++) {
            string tmp = dst + ".part";
            using (var src = e.Open()) using (var o = File.Create(tmp)) src.CopyTo(o, 1 << 20);
            if (new FileInfo(tmp).Length == e.Length) { if (File.Exists(dst)) File.Delete(dst); File.Move(tmp, dst); return; }
            File.Delete(tmp); Log("  qayta urinish: " + e.FullName);
        }
        throw new Exception("fayl to'liq ochilmadi: " + e.FullName);
    }
    static int Main(string[] a) {
        Console.OutputEncoding = Encoding.UTF8;
        string dir = Arg(a, "--dir", Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "UzLungMSKT"));
        string port = Arg(a, "--port", "8000"); bool quiet = a.Contains("--quiet");
        Directory.CreateDirectory(dir); LogPath = Path.Combine(dir, "install.log");
        Log("==== UzLungMSKT o'rnatuvchisi v2 ====  papka: " + dir + "  .NET: " + Environment.Version);
        string src = Path.GetDirectoryName(Process.GetCurrentProcess().MainModule.FileName);
        string py = Path.Combine(dir, "python", "python.exe");
        try {
            string man = Path.Combine(src, "UzLungMSKT_parts.json");
            if (!File.Exists(man)) throw new Exception("UzLungMSKT_parts.json topilmadi: exe va barcha UzLungMSKT_data_NN.zip fayllari bitta papkada bo'lishi kerak");
            string js = File.ReadAllText(man);
            var parts = Regex.Matches(js, "\"fayl\":\\s*\"([^\"]+)\",\\s*\"hajm\":\\s*(\\d+),\\s*\"sha256\":\\s*\"([0-9a-f]+)\"").Cast<Match>().Select(m => new { F = m.Groups[1].Value, N = long.Parse(m.Groups[2].Value), H = m.Groups[3].Value }).ToList();
            if (parts.Count == 0) throw new Exception("parts.json buzilgan");
            long need = parts.Sum(p => p.N) * 2; var drv = new DriveInfo(Path.GetPathRoot(Path.GetFullPath(dir)));
            Log("Diskda bo'sh joy: " + (drv.AvailableFreeSpace >> 30) + " GB (kerak ~" + (need >> 30) + " GB)");
            if (drv.AvailableFreeSpace < need) throw new Exception("diskda joy yetarli emas");
            foreach (var p in parts) {
                string f = Path.Combine(src, p.F);
                if (!File.Exists(f)) throw new Exception("qism topilmadi: " + p.F);
                if (new FileInfo(f).Length != p.N) throw new Exception("qism hajmi noto'g'ri (ko'chirishda buzilgan): " + p.F + " — faylni qayta ko'chiring");
                if (!a.Contains("--skip-verify")) { Log("Tekshirilmoqda: " + p.F); if (Sha(f) != p.H) throw new Exception("qism buzilgan (sha256 mos emas): " + p.F + " — faylni qayta ko'chiring"); }
            }
            Log("Barcha qismlar butun (" + parts.Count + " ta).");
            if (File.Exists(py) && File.Exists(Path.Combine(dir, "uzlungct", "autostart.py"))) { Log("Mavjud o'rnatma: server to'xtatilmoqda..."); Run(py, "-E -s -m uzlungct.autostart stop", dir, 60000); System.Threading.Thread.Sleep(2000); }
            int n = 0, kept = 0;
            foreach (var p in parts) {
                Log("Ochilmoqda: " + p.F);
                using (var z = ZipFile.OpenRead(Path.Combine(src, p.F))) {
                    foreach (var e in z.Entries) {
                        if (string.IsNullOrEmpty(e.Name)) continue;
                        string rel = e.FullName.Replace('/', Path.DirectorySeparatorChar);
                        if (rel.Contains("..") || Path.IsPathRooted(rel)) throw new Exception("noto'g'ri yo'l: " + rel);
                        string dst = Path.Combine(dir, rel);
                        if (rel.StartsWith("workspace" + Path.DirectorySeparatorChar) && File.Exists(dst) && !rel.Contains(Path.DirectorySeparatorChar + "runs" + Path.DirectorySeparatorChar)) { kept++; continue; }
                        Directory.CreateDirectory(Path.GetDirectoryName(dst)); Extract(e, dst); n++;
                    }
                }
            }
            Log("Fayllar ochildi: " + n + " (saqlangan foydalanuvchi fayllari: " + kept + ")");
            if (Run(py, "-E -s -c \"import uzlungct.web.server, nnunetv2, totalsegmentator, monai; print('import OK')\"", dir, 300000) != 0) throw new Exception("kutubxonalar yuklanmadi");
            string pyw = Path.Combine(dir, "python", "pythonw.exe");
            if (!a.Contains("--no-autostart")) {
                Run(py, "-E -s -m uzlungct.autostart enable --name UzLungMSKT --port " + port, dir, 60000);
                // zaxira avtostart: Startup papkasidagi yorliq (Run yozuvi o'chirilsa/bloklansa ham server yoqilganda ishga tushadi)
                MakeLnk(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Startup), "UzLungMSKT_server.lnk"), pyw,
                        "-E -s -X utf8 \"" + Path.Combine(dir, "UzLungCT_server.pyw") + "\" --port " + port, dir, "Avtostart yorlig'i");
            }
            // ish stoli yorlig'i: serverni (kerak bo'lsa) ishga tushiradi VA brauzerni ochadi
            if (!a.Contains("--no-shortcut"))
                MakeLnk(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "UzLungMSKT.lnk"), pyw,
                        "-E -s -X utf8 \"" + Path.Combine(dir, "UzLungMSKT_ochish.pyw") + "\" --port " + port, dir, "Ish stoli yorlig'i");
            Log("Server ishga tushirilmoqda: http://localhost:" + port);
            if (Run(py, "-E -s -m uzlungct.autostart start --port " + port, dir, 180000) != 0) { Log("XATO: server ishga tushmadi. Jurnal: " + Path.Combine(dir, "workspace", "logs", "web_server.log")); if (!quiet) Console.ReadLine(); return 2; }
            Log("TAYYOR: http://localhost:" + port + "  (birinchi kirish kodi: workspace\\BOSHLANGICH_ADMIN_KODI.txt)");
            if (!a.Contains("--no-browser")) Process.Start("http://localhost:" + port);
            return 0;
        } catch (Exception ex) { Log("XATO: " + ex.Message); if (!quiet) { Console.WriteLine("Enter ni bosing..."); Console.ReadLine(); } return 1; }
    }
}
