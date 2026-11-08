# Experimental Windows workflow

A graphical Windows family preview is implemented, but it has not been reviewed in a family's Windows setup. It runs one disclosed agent for the signed-in Windows account by using Task Scheduler's interactive logon trigger. It does not run before sign-in or as a machine-wide service. GitHub Actions is configured to run the Windows test suite and, after those tests pass, build and smoke-check the native package with synthetic activity. Those checks do not replace an interactive family-computer review. See Microsoft's documentation for [Task Scheduler logon triggers](https://learn.microsoft.com/en-us/windows/win32/taskschd/logontrigger-userid) and [`schtasks`](https://learn.microsoft.com/en-us/windows/win32/taskschd/schtasks).

The agent stores encrypted observations under `%LOCALAPPDATA%\Family Activity`. The public key is kept beside the encrypted database; the parent private key remains on the parent device. The preview samples foreground application names and interface byte totals, and reduces Windows IPv4/IPv6 DNS registry values and the signed-in account’s Internet Settings proxy configuration to true/false/unknown indicators. It does not retain resolver or proxy values. It checks connected status for built-in Windows VPN profiles using [`Get-VpnConnection`](https://learn.microsoft.com/en-us/powershell/module/vpnclient/get-vpnconnection?view=windowsserver2022-ps), without storing profile names. Third-party VPNs may not be detected, and separate WinHTTP proxy settings are not inspected. These settings do not establish that filtering works. When Windows can resolve the IPv4 or IPv6 default router to a neighbor MAC address, it also records a per-device HMAC hint so parents can label familiar networks. The lookup tries IPv4 first, then IPv6; within each family it sorts default routes by route plus interface metric, as described by Microsoft's [`Get-NetRoute` documentation](https://learn.microsoft.com/en-us/powershell/module/nettcpip/get-netroute), then reads the matching local neighbor-cache entry using [`Get-NetNeighbor`](https://learn.microsoft.com/en-us/powershell/module/nettcpip/get-netneighbor). The raw MAC/IP is not stored, and this hint does not prove location; routers without a usable neighbor entry remain unknown. The key is stored as a private `network.key` beside the report and is retained on normal removal. The visible tray starts at “Monitoring is starting,” changes to “Monitoring is on” after a completed encrypted sample, and changes to “Monitoring is paused” when samples are overdue (at least 45 seconds or three sampling intervals plus five seconds). If the tray helper or its heartbeat channel stops, the agent exits so Task Scheduler can restart it. Removing the task stops future sampling and retains the keys and encrypted data. Task removal checks the registered action, account, trigger, and restart settings before deleting it.


## Build and use the graphical preview

The Windows package builder runs on Windows x64 because PyInstaller cannot cross-compile the Python runtime. It expects Python 3.10 or newer with the [.NET 10 LTS SDK](https://dotnet.microsoft.com/en-us/platform/support/policy/dotnet-core), which Microsoft supports through November 14, 2028:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[build]"
.\scripts\build-windows-preview.ps1 -OutputDirectory .\dist\FamilyActivityPreview
```

The builder produces a developer folder plus an adjacent release ZIP containing a single-download installer, a short start guide, and the license. The installer contains the app bundle, copies it into the signed-in user’s Local AppData folder, then opens the existing family setup screen. It does not start monitoring until the family reviews and confirms setup. The installer accepts only safe relative archive paths, rejects symbolic links and oversized bundles, and includes a self-check for extraction and path-traversal rejection. The same platform-neutral extractor also has executable .NET tests on Linux for valid packages, traversal and rooted paths, symbolic links, duplicate names, file/folder conflicts, and incomplete bundles. The preview remains unsigned; this removes the separate manual extraction step but does not make it a supported family release. It runs `--self-test-ui`, which constructs and lays out the first-run and removal forms, checks the child disclosure and safe defaults, and exercises the tray's starting/on/paused state transitions without showing a window. It then starts a separate heartbeat IPC check that crosses the Python agent and Windows GUI executable through a real named event. The packaged core opens its loopback parent dashboard, rejects an unauthenticated API request, creates temporary encrypted test data, saves a Europe/Vienna school schedule, and renders a report using that time zone before it shuts down. A separate native Windows lifecycle check temporarily registers the actual per-user task using a renamed companion that returns only a fictional foreground app; network counters and system settings are disabled. Setup waits until the tray has signaled readiness and a new encrypted session event is stored; the validator then verifies encrypted synthetic samples, terminates the agent to test Task Scheduler restart and gap recording, removes and re-registers the task to model an update while checking that the report and parent key remain intact, then removes the task and discards the temporary report. If cleanup cannot be verified, the check preserves and reports its temporary data path. These checks do not install on a family computer or exercise the visible controls interactively. For a built preview, download and double-click `RuffsterSetup.exe` (or extract the ZIP and run the same file). It copies the app into the current Windows account and opens the setup screen; no monitoring begins until the family confirms there. On a parent's computer, choose **Open parent dashboard on this computer**; it starts the local loopback dashboard without installing monitoring. The parent key vault, settings, and encrypted reports stay in `%LOCALAPPDATA%\Family Activity Parent`. The dashboard has explicit open and stop controls. On the child's computer, choose the setup path and read the scrollable collection disclosure together before confirming it. For setup, the parent computer shows two digits and the child computer enters them; a public-key file is available if needed. The window requires a separate acknowledgment checkbox, lets the family choose child-device retention, copies the preview into `%LOCALAPPDATA%\Programs\Family Activity`, and registers a per-user sign-in task. Setup asks Task Scheduler to start it immediately and waits for the tray and an encrypted session to become ready. The same task starts at later sign-ins. A Start Menu shortcut opens settings/removal. The first-run installer also adds a Start Menu shortcut to reopen setup or the parent dashboard; after child monitoring is installed, the setup screen changes it to open settings/removal. During use, the notification-area menu explains what is recorded and can show two digits for sending an encrypted report to the parent. The parent enters them in the dashboard. Both computers need the same local network with discovery allowed; the digits only find the nearby computer. If discovery or a firewall blocks the transfer, use **Save an encrypted report file…** in the child tray menu, move that file to the parent computer, and choose **Open a report file instead** in the dashboard. The file contains encrypted records only and does not use the local network.

Removing monitoring verifies and disables the matching Ruffster task, asks Task Scheduler to end the active agent, and waits for its database lock to release before removing the task. If it cannot stop, the setup metadata and report are retained. It keeps the encrypted report by default; a second confirmation is required to also delete the local report and parent public key. After the task is removed, the setup app tries to remove its program folder when the removal window closes. The native Windows package self-check now schedules deletion of a synthetic temporary folder, keeps a marker file open to check that cleanup retries instead of deleting through the lock, then verifies the folder disappears after the lock is released. This exercises the deferred PowerShell cleanup path without touching an installation or report. The actual child setup and parent dashboard still need interactive review on a real Windows computer. The preview is unsigned. The setup/tray companion and the new self-contained installer have cross-compiled from Linux for x64; the installer embeds the bundled core and setup app. These checks prove compilation only, not the Windows installer extraction or runtime. Do not use it for ongoing family monitoring until Windows behavior, installer integrity, and the visible UI have been checked on actual supported Windows versions.

## Manual developer setup

1. Explain the collected data to the child and keep the tray indicator visible.
2. Install the project and dependencies in a Python environment for the child account. The source directory passed below must contain `family_activity\__main__.py`.
3. Build the tray helper with a Windows .NET 10 SDK. For example, from PowerShell:

   ```powershell
   dotnet publish .\native\windows\FamilyActivityStatus.csproj -c Release -r win-x64 --self-contained true
   ```

   For a compile check from Linux or macOS, install the .NET 10 SDK and allow Windows targeting packs:

   ```sh
   dotnet publish native/windows/FamilyActivityStatus.csproj -c Release -r win-x64 \
     --self-contained true -p:EnableWindowsTargeting=true \
     -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true \
     -p:EnableCompressionInSingleFile=true \
     -o /tmp/family-activity-status-win-x64
   ```

   This cross-compiles a Windows executable but cannot verify notification-area visibility, Windows event signaling, permissions, or behavior on an actual Windows session. Microsoft documents the `EnableWindowsTargeting` property for this scenario in its [NETSDK1100 guidance](https://learn.microsoft.com/en-us/dotnet/core/tools/sdk-errors/netsdk1100).

4. Export `ruffster-public.key` from the parent app, then run the explicit install command from the project directory. Replace the example paths with the actual paths on that Windows computer:

   ```powershell
   .\.venv\Scripts\python.exe -m family_activity windows-install `
     --public-key .\ruffster-public.key `
     --python .\.venv\Scripts\pythonw.exe `
     --source-directory . `
     --status-helper .\native\windows\bin\Release\net10.0-windows\win-x64\publish\FamilyActivitySetup.exe `
     --retention-days 30 `
     --disclosed
   ```

   Retention choices are 7, 30, 90, 180, or 365 days; the default is 30. Setup asks Task Scheduler to start the agent immediately, and the same task runs at later sign-ins. Task Scheduler restarts it after unexpected failures up to the configured limit and uses the least-privilege interactive token. Confirm that the icon appears in the Windows notification area before leaving the computer in use.

The agent and GUI tray helper coordinate startup through a one-run named event. The agent waits for the helper to signal readiness before collecting. A separate auto-reset event carries a heartbeat after each completed encrypted sample; the tray uses its freshness for starting, on, and paused states. This avoids depending on console output from a Windows GUI executable. The event protocol has automated mock coverage and a native package self-check, but still needs validation on Windows. The tray's “What this app records…” item explains the foreground-app and interface-total samples, minimized DNS/proxy indicators, encryption, sampling interval, retention, and data that is not collected.

## Updating an existing Windows preview

Run the newer `RuffsterSetup.exe`. For an installation with monitoring, choose **Update Ruffster**; the installed app asks the family to confirm the pause before stopping its verified task. The installer stages the new package first, waits for Ruffster windows to close, swaps the app folder, and starts the agent using the saved parent connection and retention/network settings. The encrypted report and device network key stay in `%LOCALAPPDATA%\Family Activity`. The previous app folder is kept until the updated agent confirms readiness. If readiness fails before a task registration is left uncertain, the installer restores the previous app and restarts monitoring. If task registration is uncertain, it keeps both app folders and asks the family to check the visible status before retrying.

On a computer with only the parent dashboard and no monitoring task, the installer updates app files and opens setup again. It checks that no Ruffster task is registered before changing files. The dashboard must be closed first. This is a manual update started by running a newly downloaded installer; it does not check for or download updates in the background. The transaction's directory swap and rollback have executable .NET tests, and both Windows executables cross-publish from Linux. The confirmation UI, process exit behavior, Task Scheduler stop/restart, locked-file handling, and report preservation still require a real Windows test.

5. To stop and remove the task, run:

   ```powershell
   .\.venv\Scripts\python.exe -m family_activity windows-uninstall
   ```

   The encrypted report and public key remain in `%LOCALAPPDATA%\Family Activity`.

## Not yet verified

Uninstall keeps the encrypted report by default. `family_activity windows-uninstall --delete-data` explicitly deletes the local encrypted database, SQLite sidecars and parent public key, after removing the matching task. Other copies and backups remain. The setup/tray companion has been cross-compiled from Linux to a Windows x64 GUI executable; the native GitHub Actions workflow is configured to exercise its tests and package smoke checks. Neither the full family setup nor the Windows agent has been reviewed interactively on a family Windows computer. The scheduled task, notification-area visibility, event signaling, crash-restart behavior, account changes, sleep/wake, Windows file permissions, and upgrade/removal flow still need that review. See the live [GitHub Actions runs](https://github.com/mikeymckay/ruffster/actions/workflows/ci.yml) for the current native package-check result.

## Continuous integration

The GitHub Actions workflow runs the Python test suite on Linux, macOS, and Windows, then builds and smoke-checks both platform previews on native Mac and Windows runners. It removes generated previews and does not upload or publish a Windows family download. A successful Windows runner check verifies the build and synthetic lifecycle only; it does not validate interactive family setup on a physical computer.
