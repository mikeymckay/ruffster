using System.Diagnostics;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

internal static class SetupApplication
{
    private const int RetainDaysDefault = 30;
    private static string AppFolder => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "Family Activity");
    private static string StartMenuShortcut => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.StartMenu), "Programs", "Ruffster.lnk");

    public static void Run(bool manage)
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new SetupForm(manage));
    }

    public static bool RunUpdatePreparation()
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        using var setup = new SetupForm(true, true);
        Application.Run(setup);
        return setup.UpdatePrepared;
    }

    public static void RunUiSelfTest()
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        using var setup = new SetupForm(false);
        setup.PerformLayout();
        var controls = AllControls(setup).ToArray();
        var code = controls.OfType<TextBox>().FirstOrDefault(control => control.AccessibleName == "Two digits from the parent's dashboard");
        var disclosure = controls.OfType<TextBox>().FirstOrDefault(control => control.AccessibleName == "Monitoring collection and limits");
        var confirmation = controls.OfType<CheckBox>().FirstOrDefault(control => control.AccessibleName == "Confirm the child has been told about monitoring");
        var retention = controls.OfType<ComboBox>().FirstOrDefault();
        var install = controls.OfType<Button>().FirstOrDefault(control => control.Text == "Install monitoring");
        if (setup.Text != "Set up Ruffster" || setup.ClientSize.Width != 570 ||
            code is null || code.MaxLength != 2 ||
            disclosure is null || !disclosure.ReadOnly || !disclosure.Multiline || disclosure.ScrollBars != ScrollBars.Vertical ||
            !disclosure.Text.Contains("It samples the foreground application name", StringComparison.Ordinal) ||
            !disclosure.Text.Contains("pseudonymous default-router hint", StringComparison.Ordinal) ||
            !disclosure.Text.Contains("raw router address is not saved", StringComparison.Ordinal) ||
            !disclosure.Text.Contains("rough day marker beside each encrypted record", StringComparison.Ordinal) ||
            !disclosure.Text.Contains("It does not record resolver addresses", StringComparison.Ordinal) ||
            confirmation is null || confirmation.Checked ||
            retention is null || retention.Items.Count != 5 || retention.SelectedIndex != 1 ||
            !AllControls(setup).OfType<Label>().Any(control => control.Text.Contains("calendar-day rounding may remove them up to a day before that limit", StringComparison.Ordinal)) ||
            !controls.OfType<Button>().Any(control => control.Text == "Choose connection file…") ||
            install is null)
            throw new InvalidOperationException("The Windows family setup form failed its UI self-check.");

        using var manage = new SetupForm(true);
        manage.PerformLayout();
        var manageControls = AllControls(manage).ToArray();
        var deleteData = manageControls.OfType<CheckBox>().FirstOrDefault(control =>
            control.Text.Contains("delete this computer's encrypted report", StringComparison.OrdinalIgnoreCase));
        if (manage.Text != "Ruffster settings" || manage.ClientSize.Width != 570 ||
            !manageControls.OfType<Button>().Any(control => control.Text == "Stop and remove monitoring") ||
            deleteData is null || deleteData.Checked)
            throw new InvalidOperationException("The Windows monitoring settings form failed its UI self-check.");

        using var update = new SetupForm(true, true);
        update.PerformLayout();
        var updateControls = AllControls(update).ToArray();
        if (update.Text != "Update Ruffster" ||
            !updateControls.OfType<Button>().Any(control => control.Text == "Pause monitoring and continue") ||
            updateControls.OfType<Label>().All(control => !control.Text.Contains("encrypted report", StringComparison.Ordinal)) ||
            updateControls.OfType<CheckBox>().Any())
            throw new InvalidOperationException("The Windows update confirmation form failed its UI self-check.");

        SelfTestProgramRemoval();
    }

    private static void SelfTestProgramRemoval()
    {
        var folder = Path.Combine(Path.GetTempPath(), "Ruffster removal self-test-" + Guid.NewGuid().ToString("N"));
        try
        {
            Directory.CreateDirectory(folder);
            var marker = Path.Combine(folder, "synthetic-marker.txt");
            File.WriteAllText(marker, "safe to delete");
            if (!ScheduleProgramRemoval(folder))
                throw new InvalidOperationException("The deferred Windows program-folder cleanup could not start.");
            using (var markerLock = new FileStream(marker, FileMode.Open, FileAccess.Read, FileShare.None))
            {
                System.Threading.Thread.Sleep(4000);
                if (!File.Exists(marker))
                    throw new InvalidOperationException("The deferred cleanup did not wait for a locked program file.");
            }
            var timeout = Stopwatch.StartNew();
            while (Directory.Exists(folder) && timeout.Elapsed < TimeSpan.FromSeconds(20))
                System.Threading.Thread.Sleep(100);
            if (Directory.Exists(folder))
                throw new InvalidOperationException("The deferred Windows program-folder cleanup did not finish.");
        }
        finally
        {
            if (Directory.Exists(folder)) Directory.Delete(folder, true);
        }
    }

    private static bool ScheduleProgramRemoval(string folder)
    {
        try
        {
            var powershell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),
                "WindowsPowerShell", "v1.0", "powershell.exe");
            if (!File.Exists(powershell)) return false;
            var encodedPath = Convert.ToBase64String(Encoding.Unicode.GetBytes(folder));
            var command = "$folder=[Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('" + encodedPath + "')); " +
                          "Start-Sleep -Seconds 3; for($i=0; $i -lt 20; $i++){ try { " +
                          "Remove-Item -LiteralPath $folder -Recurse -Force -ErrorAction Stop; break } " +
                          "catch { Start-Sleep -Milliseconds 500 } }";
            var start = new ProcessStartInfo(powershell)
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden,
                WorkingDirectory = Path.GetTempPath()
            };
            foreach (var argument in new[] { "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand",
                                               Convert.ToBase64String(Encoding.Unicode.GetBytes(command)) })
                start.ArgumentList.Add(argument);
            using var process = Process.Start(start);
            return process is not null;
        }
        catch { return false; }
    }

    private static IEnumerable<Control> AllControls(Control parent)
    {
        foreach (Control child in parent.Controls)
        {
            yield return child;
            foreach (var nested in AllControls(child)) yield return nested;
        }
    }

    private sealed class SetupForm : Form
    {
        private readonly bool manage;
        private readonly bool prepareUpdate;
        private readonly TextBox keyPath = new() { Width = 370, ReadOnly = true };
        private readonly TextBox code = new() { Width = 410, MaxLength = 2, AccessibleName = "Two digits from the parent's dashboard", PlaceholderText = "Enter the two digits from the parent's dashboard" };
        private readonly ComboBox retention = new() { DropDownStyle = ComboBoxStyle.DropDownList, Width = 160 };
        private readonly TextBox disclosureText = new() { Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Vertical, WordWrap = true, Width = 500, Height = 145, TabStop = true };
        private readonly CheckBox disclosed = new() { AutoSize = true, MaximumSize = new Size(500, 0) };
        private readonly CheckBox deleteData = new() { AutoSize = false, Width = 500, Height = 52 };
        private readonly Label status = new() { AutoSize = true, ForeColor = Color.DarkSlateGray };
        private readonly Button install = new() { Text = "Install monitoring", AutoSize = true };
        private readonly Button remove = new() { Text = "Stop and remove monitoring", AutoSize = true };
        private string sourceFolder = AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);

        public bool UpdatePrepared { get; private set; }

        public SetupForm(bool manageMode, bool prepareUpdateMode = false)
        {
            manage = manageMode;
            prepareUpdate = prepareUpdateMode;
            Text = prepareUpdate ? "Update Ruffster" : manage ? "Ruffster settings" : "Set up Ruffster";
            StartPosition = FormStartPosition.CenterScreen;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false; MinimizeBox = false;
            ClientSize = new Size(570, manage ? (prepareUpdate ? 340 : 400) : 700);
            Font = new Font("Segoe UI", 9.5f);

            var stack = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown, WrapContents = false, AutoScroll = true, Padding = new Padding(22) };
            Controls.Add(stack);
            stack.Controls.Add(new Label { Text = prepareUpdate ? "Review this update together" : manage ? "Monitoring settings" : "Set up together", Font = new Font(Font, FontStyle.Bold), AutoSize = true, Margin = new Padding(0, 0, 0, 8) });
            stack.Controls.Add(new Label { Text = prepareUpdate ? "Monitoring will pause while the app updates. The existing parent connection, saved settings, and encrypted report will stay on this computer. The visible status indicator will close; the new version will start monitoring again after the update.": manage ? "This preview runs for the signed-in Windows account. Removing monitoring stops the scheduled task. Your encrypted report stays on this computer unless you choose to delete it." : "Ruffster helps your family review computer use together. It starts when this Windows account signs in and shows a visible notification-area icon while it runs. This preview supports Windows 10 and 11 x64 only.", Width = 510, Height = prepareUpdate ? 82 : 60 });

            if (!manage)
            {
                var parentDashboard = new Button { Text = "Open parent dashboard on this computer…", AutoSize = true, Margin = new Padding(0, 0, 0, 8) };
                parentDashboard.Click += (_, _) => ParentDashboardLauncher.ShowFor(sourceFolder, this);
                stack.Controls.Add(parentDashboard);
                stack.Controls.Add(new Label { Text = "Use this on the parent's computer to set up private parent access and review reports. It does not install monitoring on this computer.", Width = 510, Height = 42 });
                stack.Controls.Add(new Label { Text = "Connect to your parent", Font = new Font(Font, FontStyle.Bold), AutoSize = true, Margin = new Padding(0, 6, 0, 0) });
                stack.Controls.Add(new Label { Text = "Enter the two digits shown in the parent's dashboard, or choose the connection file they shared. The parent's PIN stays on their computer.", Width = 510, Height = 48 });
                stack.Controls.Add(code);
                code.KeyPress += (_, e) => { if (!char.IsControl(e.KeyChar) && !char.IsAsciiDigit(e.KeyChar)) e.Handled = true; };
                code.TextChanged += (_, _) => { if (code.TextLength > 0) keyPath.Clear(); };
                var browse = new Button { Text = "Choose connection file…", AutoSize = true };
                browse.Click += (_, _) => ChooseKey();
                stack.Controls.Add(browse);
                stack.Controls.Add(keyPath);
                stack.Controls.Add(new Label { Text = "Keep detailed records for", AutoSize = true, Margin = new Padding(0, 8, 0, 2) });
                retention.Items.AddRange(new object[] { "7 days", "30 days", "90 days", "180 days", "365 days" });
                retention.SelectedIndex = 1;
                stack.Controls.Add(retention);
                stack.Controls.Add(new Label { Text = "This is the maximum time to keep detailed records here. Records are removed while monitoring runs; calendar-day rounding may remove them up to a day before that limit.", AutoSize = true, MaximumSize = new Size(510, 0) });
                stack.Controls.Add(new Label { Text = "What this preview records", Font = new Font(Font, FontStyle.Bold), AutoSize = true, Margin = new Padding(0, 12, 0, 4) });
                disclosureText.Text = "It samples the foreground application name about every 15 seconds, total network bytes for each interface, a pseudonymous default-router hint when one is available, and whether Windows reports IPv4/IPv6 DNS resolver settings or Internet Settings proxy configuration. The hint helps you label familiar networks; the raw router address is not saved, and the hint does not prove where the computer is. Reports are locked on this computer and can be opened on the parent's computer. It does not record resolver addresses, proxy addresses, screenshots, keystrokes, window titles, websites, audio, camera, or messages. VPN status is unknown. It starts only after this Windows account signs in, and a visible indicator should remain in the notification area.";
                disclosureText.Text += " To remove old records automatically without the parent's private key, the local report keeps a rough day marker beside each encrypted record. It can hint at when a record was added; app names, network details, and exact times stay encrypted for the parent.";
                disclosureText.Text += " The parent report may show when a new session followed an earlier session without a recorded stop. It cannot tell whether that was a crash, sleep, power-off, or another interruption.";
                disclosureText.AccessibleName = "Monitoring collection and limits";
                disclosureText.Margin = new Padding(0, 0, 0, 6);
                stack.Controls.Add(disclosureText);
                disclosed.Text = "I have explained this monitoring to the child, and they understand it will run on this account.";
                disclosed.AccessibleName = "Confirm the child has been told about monitoring";
                disclosed.Margin = new Padding(0, 4, 0, 6);
                stack.Controls.Add(disclosed);
                install.Click += async (_, _) => await InstallAsync();
                stack.Controls.Add(install);
            }
            else
            {
                if (prepareUpdate)
                {
                    remove.Text = "Pause monitoring and continue";
                    remove.Click += async (_, _) => await PrepareUpdateAsync();
                    stack.Controls.Add(remove);
                }
                else
                {
                    deleteData.Text = "Also delete this computer's encrypted report and saved connection details.";
                    deleteData.Margin = new Padding(0, 16, 0, 8);
                    stack.Controls.Add(deleteData);
                    remove.Click += async (_, _) => await RemoveAsync();
                    stack.Controls.Add(remove);
                }
            }
            status.Margin = new Padding(0, 12, 0, 0);
            stack.Controls.Add(status);
            var close = new Button { Text = "Close", AutoSize = true, DialogResult = DialogResult.Cancel, Margin = new Padding(0, 14, 0, 0) };
            stack.Controls.Add(close); CancelButton = close;
        }

        private void ChooseKey()
        {
            using var dialog = new OpenFileDialog { Title = "Choose the connection file from your parent", Filter = "Ruffster connection file|family-public.key;*.key|All files|*.*", CheckFileExists = true };
            if (dialog.ShowDialog(this) == DialogResult.OK) { keyPath.Text = dialog.FileName; code.Clear(); }
        }

        private async Task InstallAsync()
        {
            if (!disclosed.Checked) { MessageBox.Show(this, "Read the disclosure with the child and check the box to continue.", "Disclosure needed", MessageBoxButtons.OK, MessageBoxIcon.Information); return; }
            var typedCode = code.Text.Trim();
            if ((typedCode.Length == 0) == (keyPath.Text.Length == 0)) { MessageBox.Show(this, "Enter the two digits or choose the connection file from the parent.", "Parent connection needed", MessageBoxButtons.OK, MessageBoxIcon.Information); return; }
            if (typedCode.Length > 0 && (typedCode.Length != 2 || !typedCode.All(c => c >= '0' && c <= '9')))
            {
                MessageBox.Show(this, "Enter the two digits shown in the parent's dashboard. If they are not working, ask for the connection file instead.", "Check the two digits", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }
            install.Enabled = false; status.Text = "Preparing the disclosed per-user setup…";
            try
            {
                var destination = sourceFolder;
                var key = keyPath.Text;
                string? temporaryKey = null;
                try
                {
                    if (typedCode.Length > 0)
                    {
                        temporaryKey = Path.Combine(Path.GetTempPath(), "family-public-" + Guid.NewGuid().ToString("N") + ".key");
                        var fetched = await RunCoreAsync(sourceFolder, new[] { "fetch-public-key", "--code", typedCode, "--output", temporaryKey });
                        if (fetched != 0) throw new InvalidOperationException("Those digits could not connect. Ask the parent to show them again and check that both computers are on the same Wi-Fi.");
                        key = temporaryKey;
                    }
                    destination = EnsureInstalledCopy();
                    sourceFolder = destination;
                    TryCreateShortcut(destination);
                    var retentionDays = new[] { 7, 30, 90, 180, 365 }[Math.Max(0, retention.SelectedIndex)];
                    var core = Path.Combine(destination, "FamilyActivityCore", "FamilyActivityCore.exe");
                    var tray = Path.Combine(destination, "FamilyActivitySetup.exe");
                    var installArgs = new[] { "windows-install", "--public-key", key, "--python", core,
                        "--source-directory", destination, "--status-helper", tray, "--retention-days", retentionDays.ToString(), "--packaged", "--disclosed" };
                    var result = await RunCoreAsync(destination, installArgs);
                    if (result != 0) throw new InvalidOperationException("Windows could not confirm that monitoring started.");
                }
                finally { if (temporaryKey is not null) try { File.Delete(temporaryKey); } catch { } }
                TryCreateShortcut(destination);
                MessageBox.Show(this, "Setup is complete. Monitoring has started and its visible status indicator is ready. It may say ‘Monitoring is starting’ briefly until the first sample is saved, then it should say ‘Monitoring is on’. Confirm the Ruffster icon appears in the notification area or under Show hidden icons. It will also start when this Windows account signs in. The encrypted report can be shared with the parent from the icon menu.", "Ruffster is set up", MessageBoxButtons.OK, MessageBoxIcon.Information);
                Close();
            }
            catch (Exception error)
            {
                var record = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "Family Activity", "windows-install.json");
                var taskMayBeRegistered = File.Exists(record);
                var message = taskMayBeRegistered
                    ? error.Message + " A setup record is present. Do not run setup again; use Ruffster settings from the Start Menu to check or remove monitoring."
                    : error.Message + " You can correct the problem and try setup again.";
                status.Text = message;
                MessageBox.Show(this, message, "Setup could not finish", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                install.Enabled = !taskMayBeRegistered;
            }
        }

        private async Task RemoveAsync()
        {
            if (MessageBox.Show(this, "Stop monitoring for this Windows account? The encrypted report will remain on this computer unless you select delete and confirm.", "Stop Ruffster", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return;
            if (deleteData.Checked && MessageBox.Show(this, "Permanently remove the encrypted report and Ruffster connection details saved on this computer? Reports already imported to a parent computer and backups are not affected.", "Delete local report?", MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes) return;
            remove.Enabled = false; status.Text = "Stopping the scheduled agent…";
            try
            {
                var result = await RunCoreAsync(sourceFolder, deleteData.Checked ? new[] { "windows-uninstall", "--delete-data" } : new[] { "windows-uninstall" });
                if (result != 0) throw new InvalidOperationException("Windows could not verify and remove the scheduled task. Monitoring may still be configured; contact the person who set this up.");
                try { File.Delete(StartMenuShortcut); } catch { }
                var message = deleteData.Checked ? "Monitoring was stopped. The local encrypted report and connection details were deleted." : "Monitoring was stopped. The encrypted report and connection details remain in the Ruffster data folder.";
                var filesScheduled = ScheduleProgramRemoval(sourceFolder);
                message += filesScheduled
                    ? " The setup will try to remove its program files after this window closes. If the folder remains, delete it manually: " + sourceFolder + "."
                    : " The program files remain in " + sourceFolder + "; delete that folder after closing this window.";
                MessageBox.Show(this, message, "Ruffster removed", MessageBoxButtons.OK, MessageBoxIcon.Information);
                Close();
            }
            catch (Exception error)
            {
                status.Text = error.Message;
                MessageBox.Show(this, error.Message, "Could not remove monitoring", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                remove.Enabled = true;
            }
        }

        private async Task PrepareUpdateAsync()
        {
            if (MessageBox.Show(this, "Monitoring will pause while the downloaded update is installed. Continue?", "Update Ruffster", MessageBoxButtons.YesNo, MessageBoxIcon.Information) != DialogResult.Yes) return;
            remove.Enabled = false;
            status.Text = "Pausing monitoring and preserving the encrypted report…";
            try
            {
                var result = await RunCoreAsync(sourceFolder, new[] { "windows-uninstall" });
                if (result != 0) throw new InvalidOperationException("Windows could not verify and pause the scheduled agent. The update has not started; your current app and report are unchanged.");
                UpdatePrepared = true;
                status.Text = "Monitoring is paused. The installer will now replace the app files and restart monitoring.";
                Close();
            }
            catch (Exception error)
            {
                status.Text = error.Message;
                MessageBox.Show(this, error.Message, "Could not prepare the update", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                remove.Enabled = true;
            }
        }

        private string EnsureInstalledCopy()
        {
            if (Path.GetFullPath(sourceFolder).Equals(Path.GetFullPath(AppFolder), StringComparison.OrdinalIgnoreCase)) return AppFolder;
            if (Directory.Exists(AppFolder)) throw new IOException("A previous Ruffster preview folder already exists in Local AppData Programs. Remove that old preview folder before installing this copy.");
            var source = Path.GetFullPath(sourceFolder).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            var destination = Path.GetFullPath(AppFolder).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            if (destination.StartsWith(source, StringComparison.OrdinalIgnoreCase)) throw new IOException("Move the preview folder outside Local AppData Programs, then open setup again.");
            var staging = AppFolder + ".install-" + Guid.NewGuid().ToString("N");
            try { CopyBundle(sourceFolder, staging); Directory.Move(staging, AppFolder); }
            catch { try { if (Directory.Exists(staging)) Directory.Delete(staging, true); } catch { } throw; }
            return AppFolder;
        }

        private static void CopyBundle(string source, string destination)
        {
            Directory.CreateDirectory(destination);
            foreach (var dir in Directory.EnumerateDirectories(source, "*", SearchOption.AllDirectories))
            {
                if ((File.GetAttributes(dir) & FileAttributes.ReparsePoint) != 0) throw new IOException("The preview package must not contain symbolic links.");
                Directory.CreateDirectory(Path.Combine(destination, Path.GetRelativePath(source, dir)));
            }
            foreach (var file in Directory.EnumerateFiles(source, "*", SearchOption.AllDirectories))
            {
                if ((File.GetAttributes(file) & FileAttributes.ReparsePoint) != 0) throw new IOException("The preview package must not contain symbolic links.");
                var target = Path.Combine(destination, Path.GetRelativePath(source, file));
                Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                File.Copy(file, target, false);
            }
        }

        private static async Task<int> RunCoreAsync(string root, IEnumerable<string> arguments)
        {
            var core = Path.Combine(root, "FamilyActivityCore", "FamilyActivityCore.exe");
            if (!File.Exists(core)) throw new FileNotFoundException("The Ruffster application files are incomplete.", core);
            var start = new ProcessStartInfo(core) { WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true };
            foreach (var argument in arguments) start.ArgumentList.Add(argument);
            using var process = Process.Start(start) ?? throw new InvalidOperationException("The Ruffster helper could not start.");
            await process.WaitForExitAsync();
            return process.ExitCode;
        }

        private static void TryCreateShortcut(string root)
        {
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(StartMenuShortcut)!);
                var type = Type.GetTypeFromProgID("WScript.Shell");
                if (type is null) return;
                dynamic shell = Activator.CreateInstance(type)!;
                dynamic shortcut = shell.CreateShortcut(StartMenuShortcut);
                shortcut.TargetPath = Path.Combine(root, "FamilyActivitySetup.exe");
                shortcut.Arguments = "--manage";
                shortcut.WorkingDirectory = root;
                shortcut.Description = "View or remove Ruffster monitoring settings";
                shortcut.Save();
            }
            catch { /* The setup window still shows the installation path if shortcuts are unavailable. */ }
        }

    }
}
