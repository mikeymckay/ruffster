[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$OutputDirectory,
  [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Build this preview on Windows; PyInstaller does not cross-compile Python applications.' }
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Output = [System.IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path $Output) { throw "Output already exists; choose a new directory: $Output" }
$Archive = "${Output}.zip"
if (Test-Path $Archive) { throw "Archive already exists; choose a new output path: $Archive" }
& $Python -c 'import PyInstaller, nacl, cryptography, psutil'
if ($LASTEXITCODE -ne 0) { throw 'Install project dependencies and the build extra first: python -m pip install -e ".[build]"' }
$Stage = Join-Path ([System.IO.Path]::GetTempPath()) ("family-activity-win-" + [guid]::NewGuid().ToString('N'))
$Work = Join-Path $Stage 'work'
$Dist = Join-Path $Stage 'dist'
$CreatedOutput = $false
$CreatedArchive = $false
try {
  New-Item -ItemType Directory -Path (Split-Path -Parent $Output) -Force | Out-Null
  New-Item -ItemType Directory -Path $Output | Out-Null
  $CreatedOutput = $true
  New-Item -ItemType Directory -Path $Stage | Out-Null
  & $Python -m PyInstaller --noconfirm --clean --onedir --windowed --name FamilyActivityCore `
    --paths $Root --add-data "$Root\family_activity\parent_assets;family_activity\parent_assets" `
    --collect-all tzdata `
    --distpath $Dist --workpath $Work --specpath $Stage (Join-Path $Root 'scripts\frozen_main.py')
  if ($LASTEXITCODE -ne 0) { throw 'Could not bundle the Family Activity core.' }
  $CorePackage = Join-Path $Output 'FamilyActivityCore'
  New-Item -ItemType Directory -Path $CorePackage | Out-Null
  Copy-Item (Join-Path $Dist 'FamilyActivityCore\*') $CorePackage -Recurse
  & dotnet publish (Join-Path $Root 'native\windows\FamilyActivityStatus.csproj') -c Release -r win-x64 --self-contained true `
    -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -p:EnableCompressionInSingleFile=true `
    -o (Join-Path $Stage 'companion')
  if ($LASTEXITCODE -ne 0) { throw 'Could not build the Windows setup and visible tray companion.' }
  Copy-Item (Join-Path $Stage 'companion\FamilyActivitySetup.exe') (Join-Path $Output 'FamilyActivitySetup.exe')
  & (Join-Path $Output 'FamilyActivitySetup.exe') --self-test-ui
  if ($LASTEXITCODE -ne 0) { throw 'The Windows setup, removal, or tray state self-check failed.' }
  Copy-Item (Join-Path $Root 'LICENSE') (Join-Path $Output 'LICENSE')
  & (Join-Path $Output 'FamilyActivityCore\FamilyActivityCore.exe') --help
  if ($LASTEXITCODE -ne 0) { throw 'The packaged application core did not start.' }
  & $Python (Join-Path $Root 'scripts\validate-windows-preview-bundle.py') $Output
  if ($LASTEXITCODE -ne 0) { throw 'The packaged Windows loopback dashboard smoke check failed.' }
  & $Python (Join-Path $Root 'scripts\validate-windows-install-flow.py') $Output
  if ($LASTEXITCODE -ne 0) { throw 'The live synthetic Windows install, restart, or removal check failed.' }
  $Bundle = Join-Path $Stage 'FamilyActivityBundle.zip'
  Compress-Archive -Path (Join-Path $Output '*') -DestinationPath $Bundle -CompressionLevel Optimal
  & dotnet publish (Join-Path $Root 'native\windows\bootstrapper\FamilyActivityInstaller.csproj') -c Release -r win-x64 --self-contained true `
    -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -p:EnableCompressionInSingleFile=true `
    "-p:FamilyBundlePath=$Bundle" -o (Join-Path $Stage 'installer')
  if ($LASTEXITCODE -ne 0) { throw 'Could not build the direct-download Windows installer.' }
  Copy-Item (Join-Path $Stage 'installer\FamilyActivityInstaller.exe') (Join-Path $Output 'FamilyActivityInstaller.exe')
  & (Join-Path $Output 'FamilyActivityInstaller.exe') --self-test
  if ($LASTEXITCODE -ne 0) { throw 'The Windows installer extraction self-check failed.' }
  $ReleaseFolder = Join-Path $Stage 'release'
  New-Item -ItemType Directory -Path $ReleaseFolder | Out-Null
  Copy-Item (Join-Path $Output 'FamilyActivityInstaller.exe') $ReleaseFolder
  Copy-Item (Join-Path $Output 'LICENSE') $ReleaseFolder
  @'
Family Activity for Windows

Double-click FamilyActivityInstaller.exe and follow the family setup screen.
Files are copied to this Windows account before monitoring setup begins.
Monitoring starts only after the family reviews and confirms what is collected.
'@ | Set-Content -LiteralPath (Join-Path $ReleaseFolder 'START-HERE.txt') -Encoding utf8
  $CreatedArchive = $true
  Compress-Archive -Path (Join-Path $ReleaseFolder '*') -DestinationPath $Archive -CompressionLevel Optimal
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $Zip = [System.IO.Compression.ZipFile]::OpenRead($Archive)
  try {
    $Entries = @($Zip.Entries | ForEach-Object { $_.FullName })
    foreach ($RequiredEntry in @('FamilyActivityInstaller.exe', 'START-HERE.txt', 'LICENSE')) {
      if ($Entries -notcontains $RequiredEntry) { throw "The Windows preview archive is missing $RequiredEntry" }
    }
  } finally { $Zip.Dispose() }
  Write-Output "Windows x64 preview folder: $Output"
  Write-Output "Windows x64 preview archive: $Archive"
} catch {
  if ($CreatedArchive -and (Test-Path $Archive)) { Remove-Item $Archive -Force }
  if ($CreatedOutput -and (Test-Path $Output)) { Remove-Item $Output -Recurse -Force }
  throw
} finally {
  if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
}
