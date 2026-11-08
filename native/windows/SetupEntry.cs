using System.Windows.Forms;
using System.Text;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        if (Path.GetFileName(Environment.ProcessPath ?? string.Empty).Equals("FamilyActivitySyntheticForeground.exe", StringComparison.OrdinalIgnoreCase))
        {
            var output = Encoding.UTF8.GetBytes("{\"name\":\"Synthetic Study App\",\"bundle_id\":\"org.example.synthetic-study\"}\n");
            using var standardOutput = Console.OpenStandardOutput();
            standardOutput.Write(output);
            standardOutput.Flush();
            return;
        }
        if (args.Contains("--self-test-status-ipc", StringComparer.OrdinalIgnoreCase))
        {
            try { TrayCompanion.RunHeartbeatIpcSelfTest(); }
            catch { Environment.ExitCode = 1; }
            return;
        }
        if (args.Contains("--self-test-ui", StringComparer.OrdinalIgnoreCase))
        {
            try
            {
                SetupApplication.RunUiSelfTest();
                TrayCompanion.RunStatusSelfTest();
            }
            catch { Environment.ExitCode = 1; }
            return;
        }
        var manage = args.Contains("--manage", StringComparer.OrdinalIgnoreCase);
        var requestedSetup = args.Contains("--setup", StringComparer.OrdinalIgnoreCase) || manage;
        var agentPid = Environment.GetEnvironmentVariable("FAMILY_ACTIVITY_PARENT_PID");
        if (requestedSetup || string.IsNullOrWhiteSpace(agentPid)) SetupApplication.Run(manage);
        else TrayCompanion.Run();
    }
}
