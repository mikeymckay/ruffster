namespace FamilyActivity.WindowsInstall;

/// <summary>Same-volume program-folder swap used by the explicit Windows updater.</summary>
public static class DirectoryUpdate
{
    public static void Swap(string installed, string staged, string backup)
    {
        installed = Path.GetFullPath(installed);
        staged = Path.GetFullPath(staged);
        backup = Path.GetFullPath(backup);
        bool SamePath(string left, string right) => left.Equals(right, StringComparison.OrdinalIgnoreCase);
        if (SamePath(installed, staged) || SamePath(installed, backup) || SamePath(staged, backup) ||
            !string.Equals(Path.GetDirectoryName(installed), Path.GetDirectoryName(staged), StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(Path.GetDirectoryName(installed), Path.GetDirectoryName(backup), StringComparison.OrdinalIgnoreCase))
            throw new ArgumentException("The update folders must be separate siblings on the same volume.");
        if (!Directory.Exists(installed) || !Directory.Exists(staged) || Directory.Exists(backup) || File.Exists(backup))
            throw new IOException("The installed, staged, or backup app folder is not in the expected state.");

        Directory.Move(installed, backup);
        try { Directory.Move(staged, installed); }
        catch
        {
            if (!Directory.Exists(installed) && Directory.Exists(backup)) Directory.Move(backup, installed);
            throw;
        }
    }

    /// <summary>Restore the prior app and return the failed candidate folder for cleanup after readiness is confirmed.</summary>
    public static string? Restore(string installed, string backup)
    {
        installed = Path.GetFullPath(installed);
        backup = Path.GetFullPath(backup);
        if (!Directory.Exists(backup) ||
            !string.Equals(Path.GetDirectoryName(installed), Path.GetDirectoryName(backup), StringComparison.OrdinalIgnoreCase))
            throw new IOException("The previous app backup is not available for rollback.");
        if (!Directory.Exists(installed))
        {
            Directory.Move(backup, installed);
            return null;
        }
        var failed = installed + ".failed-" + Guid.NewGuid().ToString("N");
        Directory.Move(installed, failed);
        try { Directory.Move(backup, installed); }
        catch
        {
            if (!Directory.Exists(installed) && Directory.Exists(failed)) Directory.Move(failed, installed);
            throw;
        }
        return failed;
    }
}
