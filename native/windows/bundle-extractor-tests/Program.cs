using System.IO.Compression;
using FamilyActivity.WindowsInstall;

try
{
    CheckValidBundle();
    CheckUpdateSwapAndRollback();
    CheckUpdatePreflightKeepsCurrentInstall();
    CheckUpdateRestoreWhenTargetIsMissing();
    foreach (var unsafePath in new[] { "../outside.txt", "folder/../../outside.txt", "/outside.txt", "C:/outside.txt", "\\\\server\\share\\outside.txt" })
        CheckRejected("unsafe path " + unsafePath, archive => Add(archive, unsafePath, "bad"));
    CheckRejected("symbolic link", archive =>
    {
        Add(archive, "outside-link", "bad", unchecked((int)0xA0000000));
    });
    CheckRejected("duplicate names ignoring case", archive =>
    {
        AddRequired(archive);
        Add(archive, "Readme.txt", "one");
        Add(archive, "readme.TXT", "two");
    });
    CheckRejected("file and folder collision", archive =>
    {
        AddRequired(archive);
        Add(archive, "folder", "file");
        Add(archive, "folder/child.txt", "child");
    });
    CheckRejected("incomplete app bundle", archive => Add(archive, "FamilyActivitySetup.exe", "setup only"));
    Console.WriteLine("Windows installer bundle extraction tests passed.");
}
catch (Exception error)
{
    Console.Error.WriteLine(error);
    Environment.ExitCode = 1;
}

static void CheckValidBundle()
{
    using var bundle = CreateArchive(AddRequired);
    var destination = TemporaryPath();
    try
    {
        BundleExtractor.Extract(bundle, destination);
        if (File.ReadAllText(Path.Combine(destination, "FamilyActivitySetup.exe")) != "synthetic setup" ||
            File.ReadAllText(Path.Combine(destination, "FamilyActivityCore", "FamilyActivityCore.exe")) != "synthetic core")
            throw new InvalidOperationException("The valid app bundle was not extracted correctly.");
    }
    finally { Delete(destination); }
}

static void CheckUpdateSwapAndRollback()
{
    var root = TemporaryPath();
    var installed = Path.Combine(root, "Ruffster");
    var staged = Path.Combine(root, "Ruffster.update-test");
    var backup = Path.Combine(root, "Ruffster.previous-test");
    var report = Path.Combine(root, "data", "encrypted-report.sqlite3");
    try
    {
        Directory.CreateDirectory(installed);
        Directory.CreateDirectory(staged);
        Directory.CreateDirectory(Path.GetDirectoryName(report)!);
        File.WriteAllText(Path.Combine(installed, "version.txt"), "old app");
        File.WriteAllText(Path.Combine(staged, "version.txt"), "new app");
        File.WriteAllText(report, "synthetic encrypted report");

        DirectoryUpdate.Swap(installed, staged, backup);
        if (File.ReadAllText(Path.Combine(installed, "version.txt")) != "new app" ||
            File.ReadAllText(Path.Combine(backup, "version.txt")) != "old app" ||
            Directory.Exists(staged) || File.ReadAllText(report) != "synthetic encrypted report")
            throw new InvalidOperationException("The update swap did not install the staged app while preserving the previous app and report.");

        var failedCandidate = DirectoryUpdate.Restore(installed, backup)
            ?? throw new InvalidOperationException("The rollback did not keep the failed candidate aside.");
        if (File.ReadAllText(Path.Combine(installed, "version.txt")) != "old app" ||
            File.ReadAllText(Path.Combine(failedCandidate, "version.txt")) != "new app" ||
            Directory.Exists(backup) || File.ReadAllText(report) != "synthetic encrypted report")
            throw new InvalidOperationException("The update rollback did not restore the old app and retain the failed candidate and report.");
    }
    finally { Delete(root); }
}

static void CheckUpdatePreflightKeepsCurrentInstall()
{
    var root = TemporaryPath();
    var installed = Path.Combine(root, "Ruffster");
    var staged = Path.Combine(root, "Ruffster.update-test");
    var backup = Path.Combine(root, "Ruffster.previous-test");
    try
    {
        Directory.CreateDirectory(installed);
        Directory.CreateDirectory(staged);
        Directory.CreateDirectory(backup);
        File.WriteAllText(Path.Combine(backup, "previous.txt"), "keep previous");
        File.WriteAllText(Path.Combine(installed, "version.txt"), "old app");
        try
        {
            DirectoryUpdate.Swap(installed, staged, backup);
            throw new InvalidOperationException("The update accepted a pre-existing backup path.");
        }
        catch (IOException) { }
        if (!Directory.Exists(installed) ||
            File.ReadAllText(Path.Combine(installed, "version.txt")) != "old app" ||
            !Directory.Exists(staged))
            throw new InvalidOperationException("Update preflight changed the current install before validation completed.");
    }
    finally { Delete(root); }
}

static void CheckUpdateRestoreWhenTargetIsMissing()
{
    var root = TemporaryPath();
    var installed = Path.Combine(root, "Ruffster");
    var backup = Path.Combine(root, "Ruffster.previous-test");
    try
    {
        Directory.CreateDirectory(backup);
        File.WriteAllText(Path.Combine(backup, "version.txt"), "old app");
        if (DirectoryUpdate.Restore(installed, backup) is not null ||
            File.ReadAllText(Path.Combine(installed, "version.txt")) != "old app" || Directory.Exists(backup))
            throw new InvalidOperationException("The update rollback did not restore a missing app folder from its backup.");
    }
    finally { Delete(root); }
}

static void CheckRejected(string description, Action<ZipArchive> fill)
{
    using var bundle = CreateArchive(fill);
    var destination = TemporaryPath();
    try
    {
        try
        {
            BundleExtractor.Extract(bundle, destination);
            throw new InvalidOperationException("The extractor accepted " + description + ".");
        }
        catch (InvalidDataException) { }
        if (Directory.Exists(destination))
            throw new InvalidOperationException("The extractor created destination files before rejecting " + description + ".");
    }
    finally { Delete(destination); }
}

static MemoryStream CreateArchive(Action<ZipArchive> fill)
{
    var stream = new MemoryStream();
    using (var archive = new ZipArchive(stream, ZipArchiveMode.Create, true)) fill(archive);
    stream.Position = 0;
    return stream;
}

static void AddRequired(ZipArchive archive)
{
    Add(archive, "FamilyActivitySetup.exe", "synthetic setup");
    Add(archive, "FamilyActivityCore/FamilyActivityCore.exe", "synthetic core");
}

static void Add(ZipArchive archive, string path, string content, int? attributes = null)
{
    var entry = archive.CreateEntry(path, CompressionLevel.Fastest);
    if (attributes is not null) entry.ExternalAttributes = attributes.Value;
    using var output = entry.Open();
    using var input = new MemoryStream(System.Text.Encoding.UTF8.GetBytes(content));
    input.CopyTo(output);
}

static string TemporaryPath() => Path.Combine(Path.GetTempPath(), "family-installer-extractor-test-" + Guid.NewGuid().ToString("N"));
static void Delete(string path) { if (Directory.Exists(path)) Directory.Delete(path, true); }
