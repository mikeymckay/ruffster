using System.Diagnostics;
using System.IO.Compression;
using System.Reflection;
using System.Windows.Forms;

internal static class Program
{
    private const int MaxEntries = 20000;
    private const long MaxExpandedBytes = 2L * 1024 * 1024 * 1024;
    private static readonly string InstallFolder = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "Family Activity");

    [STAThread]
    private static void Main(string[] args)
    {
        if (args.Contains("--self-test", StringComparer.OrdinalIgnoreCase))
        {
            try { RunSelfTest(); }
            catch { Environment.ExitCode = 1; }
            return;
        }
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new InstallerForm());
    }

    private static void RunSelfTest()
    {
        using var bundle = new MemoryStream();
        using (var archive = new ZipArchive(bundle, ZipArchiveMode.Create, true))
        {
            AddEntry(archive, "FamilyActivitySetup.exe", "synthetic setup"u8.ToArray());
            AddEntry(archive, "FamilyActivityCore/FamilyActivityCore.exe", "synthetic core"u8.ToArray());
        }
        bundle.Position = 0;
        var destination = Path.Combine(Path.GetTempPath(), "Family Activity installer self-test-" + Guid.NewGuid().ToString("N"));
        try
        {
            ExtractBundle(bundle, destination);
            if (File.ReadAllText(Path.Combine(destination, "FamilyActivitySetup.exe")) != "synthetic setup" ||
                File.ReadAllText(Path.Combine(destination, "FamilyActivityCore", "FamilyActivityCore.exe")) != "synthetic core")
                throw new InvalidOperationException("The installer did not extract its synthetic package.");

            using var unsafeBundle = new MemoryStream();
            using (var archive = new ZipArchive(unsafeBundle, ZipArchiveMode.Create, true))
                AddEntry(archive, "../outside.txt", "must not escape"u8.ToArray());
            unsafeBundle.Position = 0;
            try
            {
                ExtractBundle(unsafeBundle, destination + "-unsafe");
                throw new InvalidOperationException("The installer accepted a path outside its destination.");
            }
            catch (InvalidDataException) { }
        }
        finally
        {
            if (Directory.Exists(destination)) Directory.Delete(destination, true);
            if (Directory.Exists(destination + "-unsafe")) Directory.Delete(destination + "-unsafe", true);
        }
    }

    private static void AddEntry(ZipArchive archive, string name, byte[] data)
    {
        var entry = archive.CreateEntry(name, CompressionLevel.Fastest);
        using var output = entry.Open();
        output.Write(data);
    }

    private static void ExtractEmbeddedBundle(string destination)
    {
        using var input = Assembly.GetExecutingAssembly().GetManifestResourceStream("FamilyActivityBundle.zip")
            ?? throw new InvalidDataException("The Family Activity package is missing from this installer.");
        ExtractBundle(input, destination);
    }

    private static void ExtractBundle(Stream input, string destination)
    {
        var root = Path.GetFullPath(destination).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        var entries = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        using var archive = new ZipArchive(input, ZipArchiveMode.Read, true);
        if (archive.Entries.Count is 0 or > MaxEntries) throw new InvalidDataException("The installer package has an invalid number of files.");
        long expanded = 0;
        var setupPresent = false;
        var corePresent = false;
        foreach (var entry in archive.Entries)
        {
            var name = entry.FullName.Replace('\\', '/');
            var directory = name.EndsWith('/');
            var relative = directory ? name[..^1] : name;
            if (string.IsNullOrWhiteSpace(relative) || relative.StartsWith('/') || Path.IsPathRooted(relative) ||
                relative.Contains(':') || relative.Split('/').Any(part => part is "" or "." or ".."))
                throw new InvalidDataException("The installer package contains an unsafe file path.");
            var unixType = (entry.ExternalAttributes >> 16) & 0xF000;
            if (unixType == 0xA000) throw new InvalidDataException("The installer package must not contain symbolic links.");
            var target = Path.GetFullPath(Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar)));
            if (!target.StartsWith(root, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("The installer package contains a file outside its install folder.");
            if (!entries.Add(target)) throw new InvalidDataException("The installer package contains duplicate file paths.");
            if (!directory)
            {
                expanded = checked(expanded + entry.Length);
                if (expanded > MaxExpandedBytes) throw new InvalidDataException("The installer package is unexpectedly large.");
                setupPresent |= relative.Equals("FamilyActivitySetup.exe", StringComparison.OrdinalIgnoreCase);
                corePresent |= relative.Equals("FamilyActivityCore/FamilyActivityCore.exe", StringComparison.OrdinalIgnoreCase);
            }
        }
        if (!setupPresent || !corePresent) throw new InvalidDataException("The installer package is incomplete.");
        Directory.CreateDirectory(root);
        foreach (var entry in archive.Entries)
        {
            var name = entry.FullName.Replace('\\', '/');
            var directory = name.EndsWith('/');
            var relative = directory ? name[..^1] : name;
            var target = Path.GetFullPath(Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar)));
            if (directory) Directory.CreateDirectory(target);
            else
            {
                Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                using var source = entry.Open();
                using var output = new FileStream(target, FileMode.CreateNew, FileAccess.Write, FileShare.None);
                source.CopyTo(output);
            }
        }
    }

    private sealed class InstallerForm : Form
    {
        private readonly Label status = new() { AutoSize = true, MaximumSize = new Size(455, 0) };
        private readonly Button install = new() { Text = "Continue to setup", AutoSize = true };
        private readonly ProgressBar progress = new() { Style = ProgressBarStyle.Marquee, MarqueeAnimationSpeed = 24, Width = 455, Visible = false };
        private bool alreadyInstalled;

        public InstallerForm()
        {
            Text = "Install Family Activity";
            StartPosition = FormStartPosition.CenterScreen;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false; MinimizeBox = false;
            ClientSize = new Size(510, 310);
            Font = new Font("Segoe UI", 9.5f);
            var stack = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown,
                WrapContents = false, Padding = new Padding(24) };
            Controls.Add(stack);
            stack.Controls.Add(new Label { Text = "A clear view of computer use, together", AutoSize = true,
                Font = new Font(Font, FontStyle.Bold), Margin = new Padding(0, 0, 0, 10) });
            stack.Controls.Add(new Label { Text = "This first step only copies Family Activity to your Windows account. Monitoring will not start until the next screen, where your family reviews what is collected and confirms setup together.", Width = 455, Height = 80 });
            status.Text = "Files will be placed in your Windows account. No administrator permission is needed.";
            stack.Controls.Add(status); stack.Controls.Add(progress);
            var buttons = new FlowLayoutPanel { AutoSize = true, FlowDirection = FlowDirection.LeftToRight,
                Margin = new Padding(0, 12, 0, 0) };
            var cancel = new Button { Text = "Cancel", AutoSize = true, DialogResult = DialogResult.Cancel };
            buttons.Controls.Add(install); buttons.Controls.Add(cancel); stack.Controls.Add(buttons);
            install.Click += async (_, _) =>
            {
                if (alreadyInstalled) LaunchSetup("--manage");
                else await InstallAsync();
            };
            CancelButton = cancel;
            Shown += (_, _) => OpenExistingIfPresent();
        }

        private void OpenExistingIfPresent()
        {
            if (!File.Exists(Path.Combine(InstallFolder, "FamilyActivitySetup.exe"))) return;
            alreadyInstalled = true;
            status.Text = "Family Activity is already installed. You can open its settings, or remove the older preview before installing this copy.";
            install.Text = "Open Family Activity settings";
        }

        private async Task InstallAsync()
        {
            install.Enabled = false; progress.Visible = true; status.Text = "Copying app files to this Windows account…";
            var target = Path.GetFullPath(InstallFolder);
            var staging = target + ".install-" + Guid.NewGuid().ToString("N");
            try
            {
                await Task.Run(() =>
                {
                    if (Directory.Exists(target)) throw new IOException("A Family Activity folder already exists. Open its settings and remove it before installing this preview.");
                    ExtractEmbeddedBundle(staging);
                    Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                    Directory.Move(staging, target);
                });
                status.Text = "Files are ready. Opening the family setup…";
                if (!LaunchSetup("--setup"))
                {
                    try { if (Directory.Exists(target)) Directory.Delete(target, true); } catch { }
                    throw new IOException("The setup screen could not be opened. Run this installer again to retry.");
                }
                TryCreateShortcut(target);
                Close();
            }
            catch (Exception error)
            {
                try { if (Directory.Exists(staging)) Directory.Delete(staging, true); } catch { }
                status.Text = error.Message;
                progress.Visible = false; install.Enabled = true;
            }
        }

        private bool LaunchSetup(string arguments)
        {
            try
            {
                var setup = Path.Combine(InstallFolder, "FamilyActivitySetup.exe");
                if (!File.Exists(setup)) return false;
                if (Process.Start(new ProcessStartInfo(setup) { UseShellExecute = true, Arguments = arguments }) is null) return false;
                Close();
                return true;
            }
            catch (Exception error) { status.Text = "Could not open Family Activity setup: " + error.Message; return false; }
        }

        private static void TryCreateShortcut(string root)
        {
            try
            {
                var shortcutPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.StartMenu),
                    "Programs", "Family Activity.lnk");
                Directory.CreateDirectory(Path.GetDirectoryName(shortcutPath)!);
                var type = Type.GetTypeFromProgID("WScript.Shell");
                if (type is null) return;
                dynamic shell = Activator.CreateInstance(type)!;
                dynamic shortcut = shell.CreateShortcut(shortcutPath);
                shortcut.TargetPath = Path.Combine(root, "FamilyActivitySetup.exe");
                shortcut.Arguments = "--setup";
                shortcut.WorkingDirectory = root;
                shortcut.Description = "Open Family Activity setup and parent dashboard";
                shortcut.Save();
            }
            catch { /* Setup can still be opened from the Local AppData program folder. */ }
        }
    }
}
