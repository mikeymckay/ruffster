using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.Net;
using System.Net.Sockets;
using System.Windows.Forms;

// Visible Windows notification-area companion for the disclosed preview.
internal static class TrayCompanion
{
    private enum TrayState { Starting, On, Paused }
    private static Process? activeShare;
    private static Form? activeShareForm;
    private static Process? activeExport;
    private static Form? activeExportForm;

    private static TrayState ResolveState(TimeSpan uptime, TimeSpan? lastHeartbeat, TimeSpan staleAfter)
    {
        if (lastHeartbeat is null) return uptime <= staleAfter ? TrayState.Starting : TrayState.Paused;
        return uptime - lastHeartbeat.Value <= staleAfter ? TrayState.On : TrayState.Paused;
    }

    private static TimeSpan ResolveStaleAfter(double sampleInterval)
    {
        if (!double.IsFinite(sampleInterval) || sampleInterval <= 0 || sampleInterval > 3600) sampleInterval = 15;
        return TimeSpan.FromSeconds(Math.Max(45, sampleInterval * 3 + 5));
    }

    public static void RunStatusSelfTest()
    {
        var timeout = TimeSpan.FromSeconds(45);
        if (ResolveState(TimeSpan.Zero, null, timeout) != TrayState.Starting ||
            ResolveState(TimeSpan.FromSeconds(46), null, timeout) != TrayState.Paused ||
            ResolveState(TimeSpan.FromSeconds(30), TimeSpan.FromSeconds(10), timeout) != TrayState.On ||
            ResolveState(TimeSpan.FromSeconds(70), TimeSpan.FromSeconds(10), timeout) != TrayState.Paused)
            throw new InvalidOperationException("The Windows tray status state check failed.");
        if (ResolveStaleAfter(double.PositiveInfinity) != TimeSpan.FromSeconds(50) ||
            ResolveStaleAfter(3600.01) != TimeSpan.FromSeconds(50) ||
            ResolveStaleAfter(3600) != TimeSpan.FromSeconds(10805))
            throw new InvalidOperationException("The Windows tray sampling-interval check failed.");
    }

    public static void RunReportExportUiSelfTest() => ExportProgressForm.RunSelfTest();

    public static void RunHeartbeatIpcSelfTest()
    {
        var readyName = Environment.GetEnvironmentVariable("FAMILY_ACTIVITY_READY_EVENT");
        var heartbeatName = Environment.GetEnvironmentVariable("FAMILY_ACTIVITY_HEARTBEAT_EVENT");
        if (string.IsNullOrWhiteSpace(readyName) || string.IsNullOrWhiteSpace(heartbeatName))
            throw new InvalidOperationException("The Windows tray heartbeat self-test is missing its event names.");
        using var heartbeat = new EventWaitHandle(false, EventResetMode.AutoReset, heartbeatName);
        using var ready = EventWaitHandle.OpenExisting(readyName);
        ready.Set();
        if (!heartbeat.WaitOne(10000))
            throw new InvalidOperationException("The Windows tray heartbeat self-test timed out.");
    }

    [STAThread]
    public static void Run()
    {
        if (!int.TryParse(Environment.GetEnvironmentVariable("FAMILY_ACTIVITY_PARENT_PID"), out int parentId)) return;
        Process parent;
        try { parent = Process.GetProcessById(parentId); }
        catch (ArgumentException) { return; }

        var heartbeatName = Environment.GetEnvironmentVariable("FAMILY_ACTIVITY_HEARTBEAT_EVENT");
        if (string.IsNullOrWhiteSpace(heartbeatName)) return;
        EventWaitHandle heartbeat;
        try { heartbeat = new EventWaitHandle(false, EventResetMode.AutoReset, heartbeatName); }
        catch { return; }
        using var heartbeatSignal = heartbeat;

        Application.EnableVisualStyles();
        using var menu = new ContextMenuStrip();
        var statusItem = new ToolStripMenuItem("Monitoring is starting")
        {
            Enabled = false,
            AccessibleName = "Monitoring status",
            AccessibleDescription = "Waiting for the first completed encrypted sample."
        };
        menu.Items.Add(statusItem);
        menu.Items.Add("What this app records…", null, (_, _) => ShowDisclosure());
        var core = Environment.GetEnvironmentVariable("FAMILY_ACTIVITY_SHARE_PYTHON");
        var database = Environment.GetEnvironmentVariable("FAMILY_ACTIVITY_SHARE_DATABASE");
        if (!string.IsNullOrWhiteSpace(core) && !string.IsNullOrWhiteSpace(database))
        {
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add("Share an encrypted report…", null, (_, _) => ShareReport(core, database));
            menu.Items.Add("Save an encrypted report file…", null, (_, _) => SaveEncryptedReport(core, database));
        }
        using var icon = new NotifyIcon { Icon = SystemIcons.Information, Text = "Ruffster: Starting", ContextMenuStrip = menu, Visible = true };
        var uptime = Stopwatch.StartNew();
        TimeSpan? lastHeartbeat = null;
        var sampleInterval = 15.0;
        if (!double.TryParse(Environment.GetEnvironmentVariable("FAMILY_ACTIVITY_SAMPLE_INTERVAL"), NumberStyles.Float,
                             CultureInfo.InvariantCulture, out sampleInterval) || !double.IsFinite(sampleInterval) || sampleInterval <= 0 || sampleInterval > 3600)
            sampleInterval = 15.0;
        var staleAfter = ResolveStaleAfter(sampleInterval);
        using var timer = new System.Windows.Forms.Timer { Interval = 2000 };
        timer.Tick += (_, _) =>
        {
            if (parent.HasExited)
            {
                try { activeShareForm?.Close(); } catch { }
                try { if (activeShare is { HasExited: false } && !activeShare.WaitForExit(2000)) activeShare.Kill(true); } catch { }
                try { activeExportForm?.Close(); } catch { }
                try { if (activeExport is { HasExited: false } && !activeExport.WaitForExit(2000)) activeExport.Kill(true); } catch { }
                Application.ExitThread();
                return;
            }
            if (heartbeatSignal.WaitOne(0)) lastHeartbeat = uptime.Elapsed;
            var elapsed = uptime.Elapsed;
            var state = ResolveState(elapsed, lastHeartbeat, staleAfter);
            statusItem.Text = state switch
            {
                TrayState.Starting => "Monitoring is starting",
                TrayState.On => "Monitoring is on",
                _ => "Monitoring is paused",
            };
            statusItem.AccessibleDescription = state switch
            {
                TrayState.Starting => "Waiting for the first completed encrypted sample.",
                TrayState.On => "Ruffster recently saved a sample. This confirms the monitor is running, not whether someone is using the computer.",
                _ => "No recent sample was saved. Some time may be missing from the report; let your parent know.",
            };
            icon.Text = state switch
            {
                TrayState.Starting => "Ruffster: Starting",
                TrayState.On => "Ruffster: Monitoring on",
                _ => "Ruffster: Monitoring paused",
            };
        };
        timer.Start();
        var readyName = Environment.GetEnvironmentVariable("FAMILY_ACTIVITY_READY_EVENT");
        if (string.IsNullOrWhiteSpace(readyName)) return;
        try
        {
            using var ready = EventWaitHandle.OpenExisting(readyName);
            ready.Set();
        }
        catch (WaitHandleCannotBeOpenedException) { return; }
        catch (UnauthorizedAccessException) { return; }
        Application.Run();
        icon.Visible = false;
        parent.Dispose();
    }

    private static void ShowDisclosure()
    {
        if (!int.TryParse(Environment.GetEnvironmentVariable("FAMILY_ACTIVITY_RETENTION_DAYS"), out int retentionDays) || retentionDays <= 0) retentionDays = 30;
        if (!double.TryParse(Environment.GetEnvironmentVariable("FAMILY_ACTIVITY_SAMPLE_INTERVAL"), NumberStyles.Float,
                             CultureInfo.InvariantCulture, out double interval) || interval <= 0) interval = 15;
        var message = $"Ruffster helps your family understand computer use. While this visible icon is running, Ruffster samples the foreground app name about every {interval:0.#} seconds and records total network bytes by interface, a private hint for the default router when available, and whether Windows reports DNS or proxy settings. The router, DNS, and proxy addresses are not saved; the router hint does not show where the computer is. VPN status is unknown. Ruffster doesn't record window titles, website addresses, screenshots, typing, messages, sound, or camera. " +
                      $"Reports are locked on this computer and can be opened on your parent's computer. Detailed records are kept for up to {retentionDays} days. Removing Ruffster keeps the report unless your parent chooses to delete it. If the icon says monitoring is paused, some time may be missing from the report; let your parent know.";
        MessageBox.Show(message, "About Ruffster", MessageBoxButtons.OK, MessageBoxIcon.Information);
    }

    private static void ShareReport(string core, string database)
    {
        try
        {
            var consent = MessageBox.Show(
                "This temporary transfer needs both computers on the same trusted Wi-Fi. Windows may ask whether Ruffster can communicate on the network. Allow it only on a private network you trust; never turn off the firewall or allow public networks. If access is blocked, cancel and choose Save an encrypted report file instead.",
                "Share an encrypted report", MessageBoxButtons.OKCancel, MessageBoxIcon.Information);
            if (consent != DialogResult.OK) return;
            var host = SelectLocalIPv4();
            var codePath = Path.Combine(Path.GetTempPath(), "family-report-code-" + Guid.NewGuid().ToString("N") + ".txt");
            var cancelPath = Path.Combine(Path.GetTempPath(), "family-report-cancel-" + Guid.NewGuid().ToString("N") + ".txt");
            var start = new ProcessStartInfo(core) { UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = Path.GetDirectoryName(core)! };
            foreach (var arg in new[] { "share", "--db", database, "--host", host, "--lifetime", "300", "--code-file", codePath, "--cancel-file", cancelPath }) start.ArgumentList.Add(arg);
            var share = Process.Start(start) ?? throw new InvalidOperationException("The encrypted report share could not start.");
            activeShare = share;
            using var form = new ShareForm(share, codePath, cancelPath);
            activeShareForm = form;
            try { form.ShowDialog(); }
            finally
            {
                activeShareForm = null; activeShare = null;
                try { File.WriteAllText(cancelPath, "stop"); } catch { }
                try { if (!share.HasExited && !share.WaitForExit(2000)) share.Kill(true); } catch { }
                try { share.Dispose(); File.Delete(codePath); File.Delete(cancelPath); } catch { }
            }
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, "Could not share the encrypted report", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private static async void SaveEncryptedReport(string core, string database)
    {
        if (activeExport is { HasExited: false })
        {
            MessageBox.Show("A report copy is already being prepared.", "Ruffster", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }
        var consent = MessageBox.Show(
            "This creates a separate file containing encrypted activity records. It does not include the parent key or PIN. Move the file to your parent computer, then choose Open a report file instead in the parent dashboard. This option does not use the local network.",
            "Save an encrypted report file?", MessageBoxButtons.OKCancel, MessageBoxIcon.Information);
        if (consent != DialogResult.OK) return;

        using var dialog = new SaveFileDialog
        {
            Title = "Save an encrypted report for your parent",
            FileName = "ruffster-report.sqlite3",
            DefaultExt = "sqlite3",
            AddExtension = true,
            OverwritePrompt = true,
            Filter = "Encrypted Ruffster report (*.sqlite3)|*.sqlite3|All files (*.*)|*.*",
            CheckPathExists = true
        };
        if (dialog.ShowDialog() != DialogResult.OK) return;

        try
        {
            var start = new ProcessStartInfo(core)
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                WorkingDirectory = Path.GetDirectoryName(core)!
            };
            foreach (var arg in new[] { "export-report", "--db", database, "--output", dialog.FileName }) start.ArgumentList.Add(arg);
            if (File.Exists(dialog.FileName)) start.ArgumentList.Add("--overwrite");
            var process = Process.Start(start) ?? throw new InvalidOperationException("The encrypted report copy could not start.");
            activeExport = process;
            using var form = new ExportProgressForm();
            activeExportForm = form;
            form.Show();
            var standardOutput = process.StandardOutput.ReadToEndAsync();
            var standardError = process.StandardError.ReadToEndAsync();
            await process.WaitForExitAsync();
            await Task.WhenAll(standardOutput, standardError);
            form.Close();
            activeExportForm = null;
            activeExport = null;
            if (process.ExitCode != 0)
            {
                var detail = standardError.Result.Trim();
                if (detail.Length > 600) detail = detail[..600];
                throw new InvalidOperationException(string.IsNullOrWhiteSpace(detail) ? "The encrypted report file could not be created." : detail);
            }
            MessageBox.Show("The encrypted report file is ready. Move it to your parent computer, then choose Open a report file instead in the parent dashboard.",
                            "Encrypted report saved", MessageBoxButtons.OK, MessageBoxIcon.Information);
            process.Dispose();
        }
        catch (Exception error)
        {
            activeExportForm = null;
            activeExport = null;
            MessageBox.Show(error.Message, "Could not save the encrypted report", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private static string SelectLocalIPv4()
    {
        using var socket = new Socket(AddressFamily.InterNetwork, SocketType.Dgram, ProtocolType.Udp);
        socket.Connect(IPAddress.Parse("192.0.2.1"), 80);
        var address = ((IPEndPoint)socket.LocalEndPoint!).Address;
        if (IPAddress.IsLoopback(address) || address.Equals(IPAddress.Any)) throw new InvalidOperationException("No local network address is available. Connect both computers to the same local network and try again.");
        return address.ToString();
    }

    private sealed class ShareForm : Form
    {
        private readonly Process process;
        private readonly string codePath;
        private readonly string cancelPath;
        private readonly TextBox code = new() { ReadOnly = true, Width = 430, Multiline = true, Height = 82, ScrollBars = ScrollBars.Vertical };
        private readonly Label detail = new() { AutoSize = true, Text = "Starting a temporary encrypted share…" };
        private readonly Button copy = new() { Text = "Copy digits", Enabled = false, AutoSize = true };
        private readonly Button closeShare = new() { Text = "Stop sharing", AutoSize = true };
        private readonly System.Windows.Forms.Timer timer = new() { Interval = 300 };
        private readonly DateTime expires = DateTime.UtcNow.AddMinutes(5);
        private bool ready;

        public ShareForm(Process runningShare, string file, string cancelFile)
        {
            process = runningShare; codePath = file; cancelPath = cancelFile;
            Text = "Share an encrypted report"; StartPosition = FormStartPosition.CenterParent;
            FormBorderStyle = FormBorderStyle.FixedDialog; MaximizeBox = false; MinimizeBox = false;
            ClientSize = new Size(500, 320); Font = new Font("Segoe UI", 9.5f);
            var stack = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown, WrapContents = false, Padding = new Padding(20) };
            Controls.Add(stack);
            stack.Controls.Add(new Label { Text = "Show these two digits to your parent", Font = new Font(Font, FontStyle.Bold), AutoSize = true });
            stack.Controls.Add(new Label { Text = "Your parent will enter them in the dashboard to receive an encrypted report. They are available for about five minutes. Keep both computers on the same trusted Wi-Fi. If the firewall blocks this, close the share and save an encrypted report file instead.", Width = 450, Height = 72 });
            stack.Controls.Add(code); stack.Controls.Add(detail);
            var buttons = new FlowLayoutPanel { AutoSize = true, FlowDirection = FlowDirection.LeftToRight, Margin = new Padding(0, 8, 0, 0) };
            copy.Click += (_, _) => { if (code.Text.Length > 0) Clipboard.SetText(code.Text); detail.Text = "Digits copied. Your parent can enter them in the dashboard."; };
            closeShare.Click += (_, _) => { if (!process.HasExited) try { File.WriteAllText(cancelPath, "stop"); } catch { } Close(); };
            buttons.Controls.Add(copy); buttons.Controls.Add(closeShare); stack.Controls.Add(buttons);
            timer.Tick += Poll; timer.Start(); FormClosed += (_, _) => { timer.Stop(); try { if (!process.HasExited) File.WriteAllText(cancelPath, "stop"); } catch { } };
        }

        private void Poll(object? sender, EventArgs e)
        {
            if (!ready && File.Exists(codePath))
            {
                try { code.Text = File.ReadAllText(codePath); ready = code.Text.Length > 0; copy.Enabled = ready; detail.Text = "Show these digits to your parent within about five minutes."; }
                catch (IOException) { }
            }
            if (!process.HasExited && ready)
            {
                var seconds = Math.Max(0, (int)(expires - DateTime.UtcNow).TotalSeconds);
                if (seconds == 0) detail.Text = "The code expired. Close this window to end the share.";
                else detail.Text = $"Available for {seconds / 60}:{seconds % 60:00}.";
            }
            else if (process.HasExited)
            {
                timer.Stop(); closeShare.Text = "Close"; copy.Enabled = false;
                detail.Text = ready ? "The transfer finished or expired. Close this window." : "The temporary share stopped before a code was ready.";
            }
        }
    }

    private sealed class ExportProgressForm : Form
    {
        private readonly Label detail = new() { Text = "Preparing the encrypted report copy…", AutoSize = true };
        private readonly ProgressBar progress = new() { Style = ProgressBarStyle.Marquee, MarqueeAnimationSpeed = 25, Width = 390 };

        public ExportProgressForm()
        {
            Text = "Saving an encrypted report"; StartPosition = FormStartPosition.CenterScreen;
            FormBorderStyle = FormBorderStyle.FixedDialog; MaximizeBox = false; MinimizeBox = false; ControlBox = false;
            ClientSize = new Size(440, 130); Font = new Font("Segoe UI", 9.5f);
            var stack = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown, WrapContents = false, Padding = new Padding(20) };
            stack.Controls.Add(new Label { Text = "Saving a copy for your parent", Font = new Font(Font, FontStyle.Bold), AutoSize = true });
            stack.Controls.Add(detail); stack.Controls.Add(progress); Controls.Add(stack);
        }

        public static void RunSelfTest()
        {
            using var form = new ExportProgressForm();
            if (form.Text != "Saving an encrypted report" || form.progress.Style != ProgressBarStyle.Marquee ||
                !form.detail.Text.Contains("encrypted report copy", StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("The encrypted report export progress UI self-check failed.");
        }
    }
}
