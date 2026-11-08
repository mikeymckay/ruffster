using System.IO.Compression;
using FamilyActivity.WindowsInstall;

try
{
    CheckValidBundle();
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
