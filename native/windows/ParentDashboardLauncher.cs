using System.Diagnostics;
using System.Drawing;
using System.Windows.Forms;

internal sealed class ParentDashboardLauncher : Form
{
    private readonly string corePath;
    private readonly string dataDirectory = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Family Activity Parent");
    private readonly string urlFile = Path.Combine(Path.GetTempPath(), "family-parent-url-" + Guid.NewGuid().ToString("N") + ".txt");
    private readonly string stopFile = Path.Combine(Path.GetTempPath(), "family-parent-stop-" + Guid.NewGuid().ToString("N") + ".txt");
    private readonly Label status = new() { AutoSize = true, MaximumSize = new Size(470, 0) };
    private readonly Button open = new() { Text = "Open dashboard", AutoSize = true, Enabled = false };
    private readonly Button stop = new() { Text = "Stop dashboard", AutoSize = true, Enabled = false };
    private readonly System.Windows.Forms.Timer timer = new() { Interval = 250 };
    private Process? server;
    private Uri? dashboardUrl;

    public static DialogResult ShowFor(string appFolder, IWin32Window owner)
    {
        using var window = new ParentDashboardLauncher(appFolder);
        return window.ShowDialog(owner);
    }

    private ParentDashboardLauncher(string appFolder)
    {
        corePath = Path.Combine(appFolder, "FamilyActivityCore", "FamilyActivityCore.exe");
        Text = "Family Activity for parents";
        StartPosition = FormStartPosition.CenterParent;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false; MinimizeBox = false;
        ClientSize = new Size(540, 310);
        Font = new Font("Segoe UI", 9.5f);

        var stack = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown,
            WrapContents = false, Padding = new Padding(22) };
        Controls.Add(stack);
        stack.Controls.Add(new Label { Text = "Your family dashboard", AutoSize = true,
            Font = new Font(Font, FontStyle.Bold), Margin = new Padding(0, 0, 0, 8) });
        stack.Controls.Add(new Label { Text = "The dashboard opens in your browser and listens only on this computer. Parent access and encrypted reports are saved in your Windows account's Local AppData folder. Unlock with your parent PIN to review reports.", Width = 480, Height = 70 });
        stack.Controls.Add(status);
        var buttons = new FlowLayoutPanel { AutoSize = true, FlowDirection = FlowDirection.LeftToRight,
            WrapContents = false, Margin = new Padding(0, 10, 0, 0) };
        buttons.Controls.Add(open); buttons.Controls.Add(stop);
        var close = new Button { Text = "Close", AutoSize = true, DialogResult = DialogResult.Cancel };
        buttons.Controls.Add(close); stack.Controls.Add(buttons);
        open.Click += (_, _) => OpenDashboard();
        stop.Click += (_, _) => { StopServer(); status.Text = "The local dashboard has stopped."; };
        timer.Tick += (_, _) => PollServer();
        Shown += (_, _) => StartServer();
        FormClosing += (_, _) => StopServer();
        CancelButton = close;
    }

    private void StartServer()
    {
        if (!File.Exists(corePath))
        {
            status.Text = "The dashboard app is missing from this preview folder. Re-extract the complete Family Activity ZIP and open this setup app again.";
            return;
        }
        try
        {
            var start = new ProcessStartInfo(corePath) { UseShellExecute = false,
                CreateNoWindow = true, WorkingDirectory = Path.GetDirectoryName(corePath)! };
            foreach (var arg in new[] { "parent", "--data-dir", dataDirectory, "--port", "0",
                                        "--no-browser", "--url-file", urlFile, "--stop-file", stopFile })
                start.ArgumentList.Add(arg);
            server = Process.Start(start) ?? throw new InvalidOperationException("The local dashboard could not start.");
            stop.Enabled = true;
            status.Text = "Starting the local dashboard…";
            timer.Start();
        }
        catch (Exception error)
        {
            status.Text = "Could not start the dashboard: " + error.Message;
        }
    }

    private void PollServer()
    {
        if (server is { HasExited: true })
        {
            timer.Stop(); stop.Enabled = false; open.Enabled = false;
            status.Text = "The dashboard has stopped. Close this window and try again.";
            return;
        }
        if (dashboardUrl is not null || !File.Exists(urlFile)) return;
        try
        {
            var text = File.ReadAllText(urlFile).Trim();
            if (text.Length == 0) return;
            if (!Uri.TryCreate(text, UriKind.Absolute, out var candidate) || candidate.Scheme != "http" ||
                candidate.Host != "127.0.0.1" || candidate.Port is < 1 or > 65535 || candidate.Fragment.Length < 20)
                throw new InvalidDataException("The local dashboard returned an invalid session address.");
            dashboardUrl = candidate;
            File.Delete(urlFile);
            status.Text = "The local dashboard is ready in your browser. Use Stop dashboard here when you are finished.";
            open.Enabled = true;
            OpenDashboard();
        }
        catch (IOException) { }
        catch (Exception error)
        {
            timer.Stop(); status.Text = "Could not open the local dashboard: " + error.Message;
        }
    }

    private void OpenDashboard()
    {
        if (dashboardUrl is null) return;
        try { Process.Start(new ProcessStartInfo(dashboardUrl.AbsoluteUri) { UseShellExecute = true }); }
        catch (Exception error) { status.Text = "The local dashboard is running, but the browser could not be opened: " + error.Message; }
    }

    private void StopServer()
    {
        timer.Stop();
        try
        {
            if (server is { HasExited: false })
            {
                File.WriteAllText(stopFile, "stop");
                if (!server.WaitForExit(5000)) server.Kill(true);
            }
        }
        catch { try { if (server is { HasExited: false }) server.Kill(true); } catch { } }
        try { server?.Dispose(); } catch { }
        server = null; dashboardUrl = null; open.Enabled = false; stop.Enabled = false;
        try { File.Delete(urlFile); } catch { }
        try { File.Delete(stopFile); } catch { }
    }
}
