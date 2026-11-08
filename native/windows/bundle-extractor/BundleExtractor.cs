using System.IO.Compression;

namespace FamilyActivity.WindowsInstall;

public static class BundleExtractor
{
    private const int MaxEntries = 20000;
    private const long MaxExpandedBytes = 2L * 1024 * 1024 * 1024;

    public static void Extract(Stream input, string destination)
    {
        var root = Path.GetFullPath(destination).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        var paths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var files = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var directories = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        using var archive = new ZipArchive(input, ZipArchiveMode.Read, true);
        if (archive.Entries.Count is 0 or > MaxEntries)
            throw new InvalidDataException("The installer package has an invalid number of files.");
        long expanded = 0;
        var setupPresent = false;
        var corePresent = false;
        foreach (var entry in archive.Entries)
        {
            var name = entry.FullName.Replace('\\', '/');
            var isDirectory = name.EndsWith('/');
            var relative = isDirectory ? name[..^1] : name;
            if (string.IsNullOrWhiteSpace(relative) || relative.StartsWith('/') || Path.IsPathRooted(relative) ||
                relative.Contains(':') || relative.Split('/').Any(part => part is "" or "." or ".."))
                throw new InvalidDataException("The installer package contains an unsafe file path.");

            var unixType = (entry.ExternalAttributes >> 16) & 0xF000;
            if (unixType == 0xA000)
                throw new InvalidDataException("The installer package must not contain symbolic links.");

            var target = Path.GetFullPath(Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar)));
            if (!target.StartsWith(root, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("The installer package contains a file outside its install folder.");
            if (!paths.Add(target))
                throw new InvalidDataException("The installer package contains duplicate file paths.");

            var segments = relative.Split('/');
            for (var index = 1; index < segments.Length; index++)
            {
                var parent = Path.GetFullPath(Path.Combine(root,
                    Path.Combine(segments[..index])));
                if (files.Contains(parent))
                    throw new InvalidDataException("The installer package has a file where a folder is required.");
                directories.Add(parent);
            }

            if (isDirectory)
            {
                if (files.Contains(target))
                    throw new InvalidDataException("The installer package has both a file and folder at the same path.");
                directories.Add(target);
            }
            else
            {
                if (directories.Contains(target))
                    throw new InvalidDataException("The installer package has a folder where a file is required.");
                files.Add(target);
                expanded = checked(expanded + entry.Length);
                if (expanded > MaxExpandedBytes)
                    throw new InvalidDataException("The installer package is unexpectedly large.");
                setupPresent |= relative.Equals("FamilyActivitySetup.exe", StringComparison.OrdinalIgnoreCase);
                corePresent |= relative.Equals("FamilyActivityCore/FamilyActivityCore.exe", StringComparison.OrdinalIgnoreCase);
            }
        }
        if (!setupPresent || !corePresent)
            throw new InvalidDataException("The installer package is incomplete.");

        Directory.CreateDirectory(root);
        foreach (var entry in archive.Entries)
        {
            var name = entry.FullName.Replace('\\', '/');
            var isDirectory = name.EndsWith('/');
            var relative = isDirectory ? name[..^1] : name;
            var target = Path.GetFullPath(Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar)));
            if (isDirectory)
                Directory.CreateDirectory(target);
            else
            {
                Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                using var source = entry.Open();
                using var output = new FileStream(target, FileMode.CreateNew, FileAccess.Write, FileShare.None);
                source.CopyTo(output);
            }
        }
    }
}
