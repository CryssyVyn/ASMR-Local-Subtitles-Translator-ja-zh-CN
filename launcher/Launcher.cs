using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;

namespace AsmrLauncher
{
    internal static class Program
    {
        internal const string CaptionTitle = "ASMR 日语 → 中文 · 本地实时字幕";
        internal static readonly string Home = AppDomain.CurrentDomain.BaseDirectory;
        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        internal static extern IntPtr FindWindow(string className, string title);
        [DllImport("user32.dll")] internal static extern bool ShowWindow(IntPtr window, int command);
        [DllImport("user32.dll")] internal static extern bool SetForegroundWindow(IntPtr window);
        [DllImport("user32.dll")] internal static extern bool ReleaseCapture();
        [DllImport("user32.dll")] internal static extern IntPtr SendMessage(IntPtr window, int message, IntPtr wparam, IntPtr lparam);
        [DllImport("user32.dll")] internal static extern bool SetProcessDPIAware();

        internal static string MissingFiles()
        {
            var missing = new List<string>();
            foreach (string file in new[] { ".venv/Scripts/python.exe", "app.py", "models/whisper-small/model.bin", "models/asmr-zh-cn-q4_k_m.gguf" })
                if (!File.Exists(Path.Combine(Home, file))) missing.Add(file);
            string engine = File.Exists(Path.Combine(Home, "cuda_ready.json")) ? "llama-cuda" : "llama";
            if (!File.Exists(Path.Combine(Home, engine, "llama-server.exe"))) missing.Add(engine + "/llama-server.exe");
            return string.Join("\n", missing.ToArray());
        }

        [STAThread]
        private static int Main(string[] args)
        {
            if (args.Length == 2 && args[0] == "--make-icon") { Artwork.WriteIcon(args[1]); return 0; }
            if (args.Length == 2 && args[0] == "--render-preview")
            {
                SetProcessDPIAware(); Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
                using (var form = new Launcher())
                using (var bitmap = new Bitmap(form.Width, form.Height))
                {
                    form.StartPosition = FormStartPosition.Manual; form.Location = new Point(-30000, -30000);
                    form.ShowInTaskbar = false; form.Opacity = 0; form.Show(); form.PerformLayout();
                    form.DrawToBitmap(bitmap, new Rectangle(Point.Empty, bitmap.Size));
                    bitmap.Save(args[1], ImageFormat.Png);
                    form.Close();
                }
                return 0;
            }
            if (args.Length == 1 && args[0] == "--self-test")
            {
                Directory.CreateDirectory(Path.Combine(Home, "work"));
                string missing = MissingFiles();
                File.WriteAllText(Path.Combine(Home, "work", "启动器自检.txt"),
                    "Launcher: " + Application.ExecutablePath + "\r\nResources: " + (missing.Length == 0 ? "OK" : missing) +
                    "\r\nApplication already running: " + (FindWindow(null, CaptionTitle) != IntPtr.Zero) + "\r\n", Encoding.UTF8);
                return missing.Length == 0 ? 0 : 1;
            }
            bool first;
            using (var mutex = new Mutex(true, "Local\\ASMRRealtime.Launcher.F_ASMRFY", out first))
            {
                if (!first)
                {
                    var window = FindWindow(null, CaptionTitle);
                    if (window == IntPtr.Zero) window = FindWindow(null, "ASMR 本地字幕 · 启动器");
                    if (window != IntPtr.Zero) { ShowWindow(window, 9); SetForegroundWindow(window); }
                    return 0;
                }
                SetProcessDPIAware();
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new Launcher());
            }
            return 0;
        }
    }

    internal static class Artwork
    {
        internal static readonly Color Teal = Color.FromArgb(93, 232, 201);
        internal static readonly Color Muted = Color.FromArgb(151, 165, 187);
        internal static GraphicsPath Rounded(RectangleF r, float radius)
        {
            float d = radius * 2;
            var p = new GraphicsPath();
            p.AddArc(r.X, r.Y, d, d, 180, 90); p.AddArc(r.Right - d, r.Y, d, d, 270, 90);
            p.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90); p.AddArc(r.X, r.Bottom - d, d, d, 90, 90);
            p.CloseFigure(); return p;
        }
        internal static Bitmap IconImage(int size)
        {
            var bitmap = new Bitmap(size, size, PixelFormat.Format32bppArgb);
            using (var g = Graphics.FromImage(bitmap))
            {
                g.SmoothingMode = SmoothingMode.AntiAlias;
                g.ScaleTransform(size / 256f, size / 256f);
                using (var p = Rounded(new RectangleF(4, 4, 248, 248), 58))
                using (var b = new LinearGradientBrush(new Point(0, 0), new Point(256, 256), Color.FromArgb(25, 48, 66), Color.FromArgb(10, 20, 35))) g.FillPath(b, p);
                using (var pen = new Pen(Teal, 15))
                {
                    pen.StartCap = pen.EndCap = LineCap.Round;
                    g.DrawArc(pen, 58, 55, 140, 142, 180, 180);
                    g.DrawLine(pen, 58, 124, 58, 167); g.DrawLine(pen, 198, 124, 198, 167);
                }
                using (var b = new SolidBrush(Teal))
                using (var left = Rounded(new RectangleF(48, 126, 31, 58), 13))
                using (var right = Rounded(new RectangleF(177, 126, 31, 58), 13)) { g.FillPath(b, left); g.FillPath(b, right); }
                using (var pen = new Pen(Color.White, 9))
                {
                    pen.StartCap = pen.EndCap = LineCap.Round;
                    g.DrawLine(pen, 103, 140, 103, 163); g.DrawLine(pen, 128, 122, 128, 183); g.DrawLine(pen, 153, 140, 153, 163);
                }
            }
            return bitmap;
        }
        internal static void WriteIcon(string path)
        {
            int[] sizes = { 16, 24, 32, 48, 64, 128, 256 };
            var images = new List<byte[]>();
            foreach (int size in sizes)
                using (var image = IconImage(size)) using (var stream = new MemoryStream()) { image.Save(stream, ImageFormat.Png); images.Add(stream.ToArray()); }
            using (var writer = new BinaryWriter(File.Create(path)))
            {
                writer.Write((ushort)0); writer.Write((ushort)1); writer.Write((ushort)sizes.Length);
                int offset = 6 + 16 * sizes.Length;
                for (int i = 0; i < sizes.Length; i++)
                {
                    writer.Write((byte)(sizes[i] == 256 ? 0 : sizes[i])); writer.Write((byte)(sizes[i] == 256 ? 0 : sizes[i]));
                    writer.Write((byte)0); writer.Write((byte)0); writer.Write((ushort)1); writer.Write((ushort)32);
                    writer.Write(images[i].Length); writer.Write(offset); offset += images[i].Length;
                }
                foreach (byte[] bytes in images) writer.Write(bytes);
            }
        }
    }

    internal sealed class ActionButton : Button
    {
        internal bool Primary;
        private bool hovered;
        internal ActionButton(bool primary)
        {
            Primary = primary; FlatStyle = FlatStyle.Flat; FlatAppearance.BorderSize = 0;
            Cursor = Cursors.Hand; Font = new Font("Microsoft YaHei UI", 11, FontStyle.Bold);
            SetStyle(ControlStyles.UserPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint, true);
        }
        protected override void OnMouseEnter(EventArgs e) { hovered = true; Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hovered = false; Invalidate(); base.OnMouseLeave(e); }
        protected override void OnPaint(PaintEventArgs e)
        {
            var g = e.Graphics; g.SmoothingMode = SmoothingMode.AntiAlias;
            using (var p = Artwork.Rounded(new RectangleF(1, 1, Width - 3, Height - 3), 13 * g.DpiX / 96f))
            using (var b = new SolidBrush(!Enabled ? Color.FromArgb(45, 66, 72) : Primary ? (hovered ? Color.FromArgb(133, 244, 218) : Artwork.Teal) : (hovered ? Color.FromArgb(38, 52, 72) : Color.FromArgb(28, 40, 59))))
            { g.FillPath(b, p); if (Focused) using (var pen = new Pen(Color.White, 1)) g.DrawPath(pen, p); }
            TextRenderer.DrawText(g, Text, Font, ClientRectangle, Primary ? Color.FromArgb(10, 39, 36) : Color.FromArgb(224, 233, 244), TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter);
        }
    }

    internal sealed class Launcher : Form
    {
        private readonly ActionButton launch;
        private readonly Label status;
        private readonly System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer();
        private Process child;
        private DateTime started;
        private StreamWriter log;
        private readonly object logLock = new object();
        private string missing;
        private bool busy;
        private bool childStarted;
        private readonly Bitmap badge = Artwork.IconImage(256);
        private readonly float layoutScale;

        internal Launcher()
        {
            Text = "ASMR 本地字幕 · 启动器";
            using (var screen = Graphics.FromHwnd(IntPtr.Zero)) layoutScale = screen.DpiX / 96f;
            ClientSize = new Size(820, 580); StartPosition = FormStartPosition.CenterScreen;
            FormBorderStyle = FormBorderStyle.None; BackColor = Color.FromArgb(13, 22, 37);
            // Bounds are designed in 96-DPI units. Fonts already use physical points;
            // scale bounds once after adding controls, leaving font sizes unchanged.
            AutoScaleMode = AutoScaleMode.None;
            DoubleBuffered = true;
            string icon = Path.Combine(Program.Home, "launcher", "ASMR.ico");
            if (File.Exists(icon)) Icon = new Icon(icon);
            AccessibleName = Text;
            var title = AddLabel("ASMR  /  本地字幕", 38, 23, 420, 30, 10, Artwork.Muted, FontStyle.Bold);
            title.MouseDown += DragWindow;
            var close = new Button { Text = "×", Bounds = new Rectangle(759, 15, 43, 40), FlatStyle = FlatStyle.Flat,
                BackColor = BackColor, ForeColor = Artwork.Muted, Font = new Font("Segoe UI", 18), Cursor = Cursors.Hand, TabStop = false, AccessibleName = "关闭启动器" };
            close.FlatAppearance.BorderSize = 0; close.Click += delegate { Close(); }; Controls.Add(close);
            var picture = new PictureBox { Image = badge, Bounds = new Rectangle(40, 110, 92, 92), SizeMode = PictureBoxSizeMode.Zoom };
            Controls.Add(picture);
            AddLabel("JAPANESE  →  CHINESE", 155, 111, 580, 30, 10, Artwork.Teal, FontStyle.Bold);
            AddLabel("听见日语，看见中文。", 150, 148, 610, 54, 24, Color.FromArgb(239, 245, 253), FontStyle.Bold);
            AddLabel("本地实时字幕，陪你安心聆听。", 42, 225, 720, 34, 12, Artwork.Muted, FontStyle.Regular);
            AddLabel("运行环境", 65, 295, 205, 28, 10, Artwork.Muted, FontStyle.Regular);
            AddLabel("日语识别", 313, 295, 205, 28, 10, Artwork.Muted, FontStyle.Regular);
            AddLabel("中文翻译", 561, 295, 205, 28, 10, Artwork.Muted, FontStyle.Regular);
            AddLabel(File.Exists(Path.Combine(Program.Home, ".venv/Scripts/python.exe")) ? "●  已安装" : "○  待安装", 65, 331, 205, 32, 12, Artwork.Teal, FontStyle.Bold);
            AddLabel(File.Exists(Path.Combine(Program.Home, "models/whisper-small/model.bin")) ? "●  模型齐全" : "○  待下载", 313, 331, 205, 32, 12, Artwork.Teal, FontStyle.Bold);
            AddLabel(File.Exists(Path.Combine(Program.Home, "models/asmr-zh-cn-q4_k_m.gguf")) ? "●  模型齐全" : "○  待下载", 561, 331, 205, 32, 12, Artwork.Teal, FontStyle.Bold);
            status = AddLabel("正在检查启动环境…", 43, 395, 735, 32, 10, Artwork.Muted, FontStyle.Regular);
            launch = new ActionButton(true) { Bounds = new Rectangle(40, 445, 492, 62), Text = "启动本地字幕  →", AccessibleName = "启动本地字幕" };
            launch.Click += StartCaption; Controls.Add(launch);
            var guide = new ActionButton(false) { Bounds = new Rectangle(550, 445, 230, 62), Text = "使用说明", AccessibleName = "打开使用说明" };
            guide.Click += delegate { OpenGuide(); }; Controls.Add(guide);
            AddLabel("全程本地处理  ·  启动后手动开始收音", 43, 535, 700, 26, 9, Artwork.Muted, FontStyle.Regular);
            MouseDown += DragWindow;
            missing = Program.MissingFiles();
            UpdateIdle(); timer.Interval = 250; timer.Tick += Tick; timer.Start();
            foreach (Control control in Controls)
            {
                Rectangle r = control.Bounds;
                control.Bounds = new Rectangle((int)Math.Round(r.X * layoutScale), (int)Math.Round(r.Y * layoutScale),
                    (int)Math.Round(r.Width * layoutScale), (int)Math.Round(r.Height * layoutScale));
            }
            ClientSize = new Size((int)Math.Round(820 * layoutScale), (int)Math.Round(580 * layoutScale));
        }
        private Label AddLabel(string text, int x, int y, int width, int height, float size, Color color, FontStyle style)
        {
            var label = new Label { Text = text, Bounds = new Rectangle(x, y, width, height), ForeColor = color,
                BackColor = Color.Transparent, Font = new Font("Microsoft YaHei UI", size, style), TextAlign = ContentAlignment.MiddleLeft };
            Controls.Add(label); return label;
        }
        private void DragWindow(object sender, MouseEventArgs e)
        {
            if (e.Button != MouseButtons.Left) return;
            Program.ReleaseCapture(); Program.SendMessage(Handle, 0xA1, new IntPtr(2), IntPtr.Zero);
        }
        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e); var g = e.Graphics; g.SmoothingMode = SmoothingMode.AntiAlias;
            g.ScaleTransform(layoutScale, layoutScale);
            using (var brush = new LinearGradientBrush(new Point(580, 40), new Point(815, 320), Color.FromArgb(24, 57, 64), BackColor))
                g.FillEllipse(brush, 580, 62, 330, 280);
            using (var p = Artwork.Rounded(new RectangleF(41, 280, 738, 99), 17))
            using (var b = new SolidBrush(Color.FromArgb(23, 35, 53))) g.FillPath(b, p);
            using (var p = new Pen(Color.FromArgb(43, 59, 77))) { g.DrawLine(p, 289, 301, 289, 358); g.DrawLine(p, 537, 301, 537, 358); }
            using (var p = new Pen(Color.FromArgb(40, 57, 76))) g.DrawRectangle(p, 0, 0, 819, 579);
        }
        private void UpdateIdle()
        {
            bool running = Program.FindWindow(null, Program.CaptionTitle) != IntPtr.Zero;
            launch.Text = running ? "返回字幕窗口  →" : "启动本地字幕  →";
            status.Text = running ? "字幕程序已打开，点击下方按钮即可返回。" : missing.Length == 0 ? "一切就绪。打开字幕窗口后，点击“开始接收播放声音”。" : "启动文件不完整，点击启动查看详情。";
        }
        private void OpenGuide()
        {
            try { Process.Start(new ProcessStartInfo("notepad.exe", "\"" + Path.Combine(Program.Home, "使用说明.md") + "\"") { UseShellExecute = true }); }
            catch (Exception exc) { MessageBox.Show(this, exc.Message, "无法打开使用说明", MessageBoxButtons.OK, MessageBoxIcon.Information); }
        }
        private void StartCaption(object sender, EventArgs e)
        {
            var window = Program.FindWindow(null, Program.CaptionTitle);
            if (window != IntPtr.Zero) { Program.ShowWindow(window, 9); Program.SetForegroundWindow(window); Close(); return; }
            missing = Program.MissingFiles();
            if (missing.Length != 0)
            {
                MessageBox.Show(this, "以下文件尚未就绪：\n\n" + missing + "\n\n模型缺失时，请运行“继续下载模型.cmd”。", "暂时无法启动", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }
            try
            {
                Directory.CreateDirectory(Path.Combine(Program.Home, "work"));
                log = new StreamWriter(Path.Combine(Program.Home, "work", "程序启动日志.txt"), false, new UTF8Encoding(false)) { AutoFlush = true };
                log.WriteLine("Launch: " + DateTimeOffset.Now.ToString("o"));
                var info = new ProcessStartInfo(Path.Combine(Program.Home, ".venv", "Scripts", "python.exe"), "-u -X faulthandler app.py")
                {
                    WorkingDirectory = Program.Home, UseShellExecute = false, CreateNoWindow = true,
                    RedirectStandardOutput = true, RedirectStandardError = true, StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
                };
                info.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
                child = new Process { StartInfo = info };
                child.OutputDataReceived += WriteLog; child.ErrorDataReceived += WriteLog;
                if (!child.Start()) throw new InvalidOperationException("未能创建字幕程序进程。");
                childStarted = true; child.BeginOutputReadLine(); child.BeginErrorReadLine();
                busy = true; started = DateTime.UtcNow; launch.Enabled = false;
                launch.Text = "正在打开字幕窗口…"; status.Text = "首次打开需要几秒钟，请稍候。";
            }
            catch (Exception exc) { Fail(exc.Message); }
        }
        private void WriteLog(object sender, DataReceivedEventArgs e)
        {
            if (e.Data == null) return;
            lock (logLock) { if (log != null) log.WriteLine(e.Data); }
        }
        private void Fail(string reason)
        {
            bool live = child != null && childStarted && !child.HasExited;
            busy = live; launch.Enabled = !live; launch.Text = live ? "正在打开字幕窗口…" : "重新启动  →";
            if (!live)
            {
                if (child != null) { if (childStarted) child.WaitForExit(); child.Dispose(); child = null; }
                childStarted = false;
                lock (logLock) { if (log != null) { log.Dispose(); log = null; } }
            }
            status.Text = "启动未完成，请查看提示。";
            MessageBox.Show(this, reason + "\n\n诊断日志：work\\程序启动日志.txt", "字幕程序未能启动", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
        private void Tick(object sender, EventArgs e)
        {
            if (!busy) { UpdateIdle(); return; }
            var window = Program.FindWindow(null, Program.CaptionTitle);
            if (window != IntPtr.Zero)
            {
                // Keep redirected output draining for the full lifetime of Python.
                // The launcher becomes an invisible supervisor; the taskbar stays clear.
                Program.ShowWindow(window, 9); Program.SetForegroundWindow(window);
                Hide(); ShowInTaskbar = false; busy = false;
                timer.Tick -= Tick; timer.Tick += MonitorExit;
                return;
            }
            if (child.HasExited)
            {
                child.WaitForExit(); Fail("程序在打开窗口前退出，退出代码：" + child.ExitCode); return;
            }
            if ((DateTime.UtcNow - started).TotalSeconds > 30)
                status.Text = "启动时间较长，正在等待字幕窗口；可在 work 文件夹查看启动日志。";
        }
        private void MonitorExit(object sender, EventArgs e) { if (child.HasExited) Close(); }
        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            // Do not break the Python stdout pipe if the user closes the launcher while it is starting.
            if (child != null && childStarted && !child.HasExited && Visible)
            {
                e.Cancel = true; Hide(); ShowInTaskbar = false; return;
            }
            base.OnFormClosing(e);
        }
        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                timer.Dispose(); badge.Dispose();
                if (child != null) { if (childStarted) child.WaitForExit(); child.Dispose(); }
                lock (logLock) { if (log != null) { log.Dispose(); log = null; } }
            }
            base.Dispose(disposing);
        }
    }
}
