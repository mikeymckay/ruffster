using System.Diagnostics;
using System.IO.Compression;
using System.Reflection;
using System.Text.Json;
using System.Windows.Forms;
using FamilyActivity.WindowsInstall;

internal static class Program
{
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
        var destination = Path.Combine(Path.GetTempPath(), "Ruffster installer self-test-" + Guid.NewGuid().ToString("N"));
        try
        {
            BundleExtractor.Extract(bundle, destination);
            if (File.ReadAllText(Path.Combine(destination, "FamilyActivitySetup.exe")) != "synthetic setup" ||
                File.ReadAllText(Path.Combine(destination, "FamilyActivityCore", "FamilyActivityCore.exe")) != "synthetic core")
                throw new InvalidOperationException("The installer did not extract its synthetic package.");

            using var unsafeBundle = new MemoryStream();
            using (var archive = new ZipArchive(unsafeBundle, ZipArchiveMode.Create, true))
                AddEntry(archive, "../outside.txt", "must not escape"u8.ToArray());
            unsafeBundle.Position = 0;
            try
            {
                BundleExtractor.Extract(unsafeBundle, destination + "-unsafe");
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
            ?? throw new InvalidDataException("The Ruffster package is missing from this installer.");
        BundleExtractor.Extract(input, destination);
    }

    private sealed class InstallerForm : Form
    {
        private readonly Label status = new() { AutoSize = true, MaximumSize = new Size(455, 0) };
        private readonly Label intro = new() { Text = "This first step only copies Ruffster to your Windows account. Monitoring will not start until the next screen, where your family reviews what is collected and confirms setup together.", Width = 455, Height = 80 };
        private readonly Button install = new() { Text = "Continue to setup", AutoSize = true };
        private readonly ProgressBar progress = new() { Style = ProgressBarStyle.Marquee, MarqueeAnimationSpeed = 24, Width = 455, Visible = false };
        private bool alreadyInstalled;
        private bool monitoringInstalled;

        public InstallerForm()
        {
            Text = "Install Ruffster";
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
            stack.Controls.Add(intro);
            status.Text = "Files will be placed in your Windows account. No administrator permission is needed.";
            stack.Controls.Add(status); stack.Controls.Add(progress);
            var buttons = new FlowLayoutPanel { AutoSize = true, FlowDirection = FlowDirection.LeftToRight,
                Margin = new Padding(0, 12, 0, 0) };
            var cancel = new Button { Text = "Cancel", AutoSize = true, DialogResult = DialogResult.Cancel };
            buttons.Controls.Add(install); buttons.Controls.Add(cancel); stack.Controls.Add(buttons);
            install.Click += async (_, _) =>
            {
                if (alreadyInstalled) await UpdateAsync();
                else await InstallAsync();
            };
            CancelButton = cancel;
            Shown += (_, _) => OpenExistingIfPresent();
        }

        private void OpenExistingIfPresent()
        {
            if (!File.Exists(Path.Combine(InstallFolder, "FamilyActivitySetup.exe"))) return;
            alreadyInstalled = true;
            monitoringInstalled = File.Exists(Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Family Activity", "windows-install.json"));
            status.Text = monitoringInstalled
                ? "Ruffster is already installed. The update keeps its encrypted report and parent connection. Monitoring will pause briefly while files are replaced."
                : "Ruffster is already installed. This computer has no registered monitoring; updating replaces only the app files. Parent reports and settings are stored separately.";
            install.Text = "Update Ruffster";
            Text = "Update Ruffster";
            intro.Text = monitoringInstalled
                ? "This update replaces the app in this Windows account. You will review and confirm the brief monitoring pause in Ruffster before any program files change."
                : "This update replaces the app files in this Windows account. It does not change parent reports or settings. If you have not set up monitoring, the family setup screen will open after the update.";
            intro.Height = 70;
        }

        private sealed record UpdateSettings(string PublicKey, int RetentionDays,
            bool MonitorNetwork, bool InspectNetworkSettings);

        private async Task UpdateAsync()
        {
            if (!monitoringInstalled)
            {
                await UpdateProgramOnlyAsync();
                return;
            }
            install.Enabled = false; progress.Visible = true;
            var target = Path.GetFullPath(InstallFolder);
            var staging = target + ".update-" + Guid.NewGuid().ToString("N");
            var backup = target + ".previous-" + Guid.NewGuid().ToString("N");
            var targetMoved = false;
            var updatePrepared = false;
            UpdateSettings? settings = null;
            try
            {
                status.Text = "Checking the existing family setup and preparing the update…";
                settings = await Task.Run(() => ReadUpdateSettings(target));
                await Task.Run(() => ExtractEmbeddedBundle(staging));
                status.Text = "Review the update on the Ruffster computer…";
                var preparation = await PrepareInstalledUpdateAsync(target);
                if (preparation != 0)
                    throw new OperationCanceledException("The update was canceled or monitoring could not be safely paused. The current app and report were kept.");
                updatePrepared = true;

                status.Text = "Closing any remaining Ruffster windows…";
                await WaitForInstalledProcessesAsync(target, TimeSpan.FromSeconds(30));
                status.Text = "Replacing app files…";
                await Task.Run(() => DirectoryUpdate.Swap(target, staging, backup));
                targetMoved = true;

                status.Text = "Starting the updated monitoring app…";
                var installed = await RunAgentInstallAsync(target, settings);
                if (installed != 0)
                {
                    var metadata = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                        "Family Activity", "windows-install.json");
                    if (File.Exists(metadata))
                    {
                        throw new IOException("The updated agent's registration could not be confirmed. The new app and the previous app backup were both kept. Open Ruffster settings to check monitoring before trying again. Previous app files: " + backup);
                    }
                    await RestorePreviousAndRestartAsync(target, backup, settings);
                    targetMoved = false;
                    updatePrepared = false;
                    MessageBox.Show(this, "The update could not start, so the previous app was restored and monitoring was restarted. Your encrypted report and parent connection were kept.", "Previous version restored", MessageBoxButtons.OK, MessageBoxIcon.Information);
                    Close();
                    return;
                }

                var backupKept = false;
                try { Directory.Delete(backup, true); }
                catch { backupKept = true; }
                targetMoved = false;
                updatePrepared = false;
                TryCreateShortcut(target);
                var completion = backupKept
                    ? "Ruffster was updated and monitoring restarted. Your encrypted report and parent connection were kept. The previous app files remain in " + backup + "."
                    : "Ruffster was updated and monitoring restarted. Your encrypted report and parent connection were kept.";
                MessageBox.Show(this, completion, "Update complete", MessageBoxButtons.OK, MessageBoxIcon.Information);
                Close();
            }
            catch (OperationCanceledException error)
            {
                status.Text = error.Message;
                progress.Visible = false; install.Enabled = true;
            }
            catch (Exception error)
            {
                var message = error.Message;
                if (updatePrepared && settings is not null)
                {
                    var metadata = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                        "Family Activity", "windows-install.json");
                    if (!File.Exists(metadata))
                    {
                        try
                        {
                            if (Directory.Exists(backup))
                                await RestorePreviousAndRestartAsync(target, backup, settings);
                            else if (await RunAgentInstallAsync(target, settings) != 0)
                                throw new IOException("Windows did not confirm monitoring restarted.");
                            targetMoved = false;
                            updatePrepared = false;
                            message += " The previous app was restored and monitoring restarted.";
                        }
                        catch (Exception recoveryError)
                        {
                            message += " Automatic recovery could not confirm that monitoring restarted: " + recoveryError.Message;
                        }
                    }
                    else
                    {
                        message += " A setup record remains, so both app folders were preserved. Open Ruffster settings and check whether monitoring is on before trying again. Previous app files: " + backup;
                    }
                }
                status.Text = message;
                progress.Visible = false; install.Enabled = true;
                MessageBox.Show(this, message, "Ruffster could not finish the update", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
            finally
            {
                try { if (Directory.Exists(staging)) Directory.Delete(staging, true); } catch { }
                if (!targetMoved && Directory.Exists(backup))
                {
                    // A backup left after an uncertain registration is deliberately retained for recovery.
                }
            }
        }

        private async Task UpdateProgramOnlyAsync()
        {
            if (MessageBox.Show(this,
                "Update the Ruffster app files on this computer? No monitoring is registered here. Parent reports and settings are stored separately and will stay in place.",
                "Update Ruffster", MessageBoxButtons.YesNo, MessageBoxIcon.Information) != DialogResult.Yes) return;
            install.Enabled = false; progress.Visible = true;
            var target = Path.GetFullPath(InstallFolder);
            var staging = target + ".update-" + Guid.NewGuid().ToString("N");
            var backup = target + ".previous-" + Guid.NewGuid().ToString("N");
            var swapped = false;
            try
            {
                status.Text = "Checking this computer and preparing the update…";
                await Task.Run(EnsureNoManagedTaskWithoutRecord);
                await Task.Run(() => ExtractEmbeddedBundle(staging));
                status.Text = "Close the Ruffster dashboard if it is open…";
                await WaitForInstalledProcessesAsync(target, TimeSpan.FromSeconds(30));
                status.Text = "Replacing app files…";
                await Task.Run(() => DirectoryUpdate.Swap(target, staging, backup));
                swapped = true;
                status.Text = "Checking the updated Ruffster screens…";
                if (await RunCompanionSelfTestAsync(target) != 0)
                    throw new IOException("The updated Ruffster screens did not pass their built-in check.");
                swapped = false;
                try { Directory.Delete(backup, true); } catch { }
                TryCreateShortcut(target);
                MessageBox.Show(this, "Ruffster was updated. Your parent reports and settings remain on this computer. The setup screen will open next.", "Update complete", MessageBoxButtons.OK, MessageBoxIcon.Information);
                if (!LaunchSetup("--setup"))
                {
                    status.Text = "The app was updated. Open Ruffster from the Start Menu when you are ready.";
                    progress.Visible = false; install.Enabled = true;
                    MessageBox.Show(this, status.Text, "Ruffster is updated", MessageBoxButtons.OK, MessageBoxIcon.Information);
                }
            }
            catch (Exception error)
            {
                var message = error.Message;
                if (swapped && Directory.Exists(backup))
                {
                    try
                    {
                        var failed = DirectoryUpdate.Restore(target, backup);
                        swapped = false;
                        if (failed is not null) try { Directory.Delete(failed, true); } catch { }
                        message += " The previous app files were restored.";
                    }
                    catch (Exception recoveryError) { message += " Automatic file recovery needs attention: " + recoveryError.Message; }
                }
                status.Text = message;
                progress.Visible = false; install.Enabled = true;
                MessageBox.Show(this, message, "Ruffster could not finish the update", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
            finally
            {
                try { if (Directory.Exists(staging)) Directory.Delete(staging, true); } catch { }
            }
        }

        private static void EnsureNoManagedTaskWithoutRecord()
        {
            var schedulerType = Type.GetTypeFromProgID("Schedule.Service")
                ?? throw new IOException("Windows Task Scheduler could not be checked safely.");
            dynamic scheduler = Activator.CreateInstance(schedulerType)
                ?? throw new IOException("Windows Task Scheduler could not be checked safely.");
            scheduler.Connect();
            dynamic folder = scheduler.GetFolder("\\");
            try
            {
                _ = folder.GetTask("FamilyActivity-Agent");
                throw new IOException("A Ruffster monitoring task exists but its setup record is missing. Open Ruffster settings and remove or repair that setup before updating.");
            }
            catch (System.Runtime.InteropServices.COMException error) when
                (error.HResult is unchecked((int)0x80070002) or unchecked((int)0x8004130F))
            {
                // The task is confirmed absent, so only app files need updating.
            }
        }

        private static async Task<int> RunCompanionSelfTestAsync(string target)
        {
            var setup = Path.Combine(target, "FamilyActivitySetup.exe");
            var start = new ProcessStartInfo(setup) { UseShellExecute = false, CreateNoWindow = true,
                WorkingDirectory = target, Arguments = "--self-test-ui" };
            using var process = Process.Start(start) ?? throw new IOException("The updated Ruffster setup could not start its screen check.");
            await process.WaitForExitAsync();
            return process.ExitCode;
        }

        private static UpdateSettings ReadUpdateSettings(string target)
        {
            var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            var data = Path.Combine(local, "Family Activity");
            var metadata = Path.Combine(data, "windows-install.json");
            foreach (var path in new[] { target, data, metadata })
            {
                if (!File.Exists(path) && !Directory.Exists(path)) throw new FileNotFoundException("The existing Ruffster installation record is missing.", path);
                if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
                    throw new IOException("Ruffster cannot update a folder redirected through a symbolic link or junction.");
            }
            using var document = JsonDocument.Parse(File.ReadAllText(metadata));
            var root = document.RootElement;
            if (root.GetProperty("version").GetInt32() != 1) throw new InvalidDataException("The existing Ruffster setup record is not supported by this updater.");
            var identity = root.GetProperty("identity");
            var expectedDatabase = Path.Combine(data, "activity.sqlite3");
            var expectedPublicKey = Path.Combine(data, "parent.pub");
            var expectedNetworkKey = Path.Combine(data, "network.key");
            bool SamePath(string actual, string expected) => Path.GetFullPath(actual).Equals(Path.GetFullPath(expected), StringComparison.OrdinalIgnoreCase);
            if (identity.GetProperty("task_name").GetString() != "FamilyActivity-Agent" ||
                !identity.GetProperty("packaged").GetBoolean() ||
                !SamePath(identity.GetProperty("source").GetString() ?? "", target) ||
                !SamePath(identity.GetProperty("database").GetString() ?? "", expectedDatabase) ||
                !SamePath(identity.GetProperty("public_key").GetString() ?? "", expectedPublicKey) ||
                (identity.TryGetProperty("network_key", out var networkKey) &&
                 !SamePath(networkKey.GetString() ?? "", expectedNetworkKey)) ||
                identity.TryGetProperty("foreground_helper", out var foreground) && foreground.ValueKind != JsonValueKind.Null)
                throw new InvalidDataException("This update only supports a standard Ruffster per-user installation. The current setup was not changed.");
            var retention = identity.GetProperty("retention_days").GetInt32();
            if (retention is not (7 or 30 or 90 or 180 or 365)) throw new InvalidDataException("The existing report-retention setting is not supported by this updater.");
            var monitorNetwork = !identity.TryGetProperty("monitor_network", out var monitor) || monitor.GetBoolean();
            var inspectNetwork = !identity.TryGetProperty("inspect_network_settings", out var inspect) || inspect.GetBoolean();
            if (inspectNetwork && !monitorNetwork) throw new InvalidDataException("The existing network settings are inconsistent. The current setup was not changed.");
            if (!File.Exists(expectedPublicKey)) throw new FileNotFoundException("The saved parent connection was not found; the current setup was not changed.", expectedPublicKey);
            return new UpdateSettings(expectedPublicKey, retention, monitorNetwork, inspectNetwork);
        }

        private static async Task<int> PrepareInstalledUpdateAsync(string target)
        {
            var setup = Path.Combine(target, "FamilyActivitySetup.exe");
            var start = new ProcessStartInfo(setup) { UseShellExecute = true, Arguments = "--prepare-update" };
            using var process = Process.Start(start) ?? throw new IOException("The installed Ruffster update confirmation could not be opened.");
            await process.WaitForExitAsync();
            return process.ExitCode;
        }

        private static async Task WaitForInstalledProcessesAsync(string target, TimeSpan timeout)
        {
            var root = Path.GetFullPath(target).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            var deadline = DateTime.UtcNow + timeout;
            while (DateTime.UtcNow < deadline)
            {
                var active = false;
                foreach (var process in Process.GetProcesses())
                {
                    using (process)
                    {
                        try
                        {
                            if (process.HasExited) continue;
                            var executable = process.MainModule?.FileName;
                            if (!string.IsNullOrWhiteSpace(executable) &&
                                Path.GetFullPath(executable).StartsWith(root, StringComparison.OrdinalIgnoreCase))
                                active = true;
                        }
                        catch (System.ComponentModel.Win32Exception)
                        {
                            if (process.ProcessName.StartsWith("FamilyActivity", StringComparison.OrdinalIgnoreCase)) active = true;
                        }
                        catch (InvalidOperationException) { }
                    }
                    if (active) break;
                }
                if (!active) return;
                await Task.Delay(250);
            }
            throw new IOException("A Ruffster window is still closing. Close the dashboard or tray windows and run the update again.");
        }

        private static async Task<int> RunAgentInstallAsync(string target, UpdateSettings settings)
        {
            var core = Path.Combine(target, "FamilyActivityCore", "FamilyActivityCore.exe");
            var start = new ProcessStartInfo(core) { UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = target };
            foreach (var argument in new[] { "windows-install", "--public-key", settings.PublicKey,
                "--python", core, "--source-directory", target, "--status-helper",
                Path.Combine(target, "FamilyActivitySetup.exe"), "--retention-days", settings.RetentionDays.ToString(),
                "--packaged", "--disclosed" }) start.ArgumentList.Add(argument);
            if (!settings.MonitorNetwork) start.ArgumentList.Add("--no-network");
            if (!settings.InspectNetworkSettings) start.ArgumentList.Add("--no-network-settings");
            using var process = Process.Start(start) ?? throw new IOException("The updated Ruffster agent could not start.");
            await process.WaitForExitAsync();
            return process.ExitCode;
        }

        private static async Task RestorePreviousAndRestartAsync(string target, string backup, UpdateSettings settings)
        {
            var failed = DirectoryUpdate.Restore(target, backup);
            var result = await RunAgentInstallAsync(target, settings);
            if (result != 0) throw new IOException("The previous app files were restored, but Windows did not confirm monitoring restarted. Open Ruffster settings and check the status." + (failed is null ? "" : " The update files were kept at " + failed + "."));
            if (failed is not null) try { Directory.Delete(failed, true); } catch { }
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
                    if (Directory.Exists(target)) throw new IOException("A Ruffster folder already exists. Open its settings and remove it before installing this preview.");
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
            catch (Exception error) { status.Text = "Could not open Ruffster setup: " + error.Message; return false; }
        }

        private static void TryCreateShortcut(string root)
        {
            try
            {
                var shortcutPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.StartMenu),
                    "Programs", "Ruffster.lnk");
                Directory.CreateDirectory(Path.GetDirectoryName(shortcutPath)!);
                var type = Type.GetTypeFromProgID("WScript.Shell");
                if (type is null) return;
                dynamic shell = Activator.CreateInstance(type)!;
                dynamic shortcut = shell.CreateShortcut(shortcutPath);
                shortcut.TargetPath = Path.Combine(root, "FamilyActivitySetup.exe");
                shortcut.Arguments = "--setup";
                shortcut.WorkingDirectory = root;
                shortcut.Description = "Open Ruffster setup and parent dashboard";
                shortcut.Save();
            }
            catch { /* Setup can still be opened from the Local AppData program folder. */ }
        }
    }
}
