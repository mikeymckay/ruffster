from pathlib import Path
import unittest


class WindowsSetupDisclosureTests(unittest.TestCase):
    def test_windows_preview_compresses_self_contained_companion(self):
        root = Path(__file__).parents[1]
        source = (root / 'scripts/build-windows-preview.ps1').read_text(encoding='utf-8')
        project = (root / 'native/windows/FamilyActivityStatus.csproj').read_text(encoding='utf-8')
        self.assertIn('-p:PublishSingleFile=true', source)
        self.assertIn('-p:IncludeNativeLibrariesForSelfExtract=true', source)
        self.assertIn('-p:EnableCompressionInSingleFile=true', source)
        self.assertIn('<TreatWarningsAsErrors>true</TreatWarningsAsErrors>', project)

    def test_direct_download_installer_embeds_bundle_and_checks_extraction_paths(self):
        root = Path(__file__).parents[1]
        source = (root / 'native/windows/bundle-extractor/BundleExtractor.cs').read_text(encoding='utf-8')
        installer = (root / 'native/windows/bootstrapper/Program.cs').read_text(encoding='utf-8')
        project = (root / 'native/windows/bootstrapper/FamilyActivityInstaller.csproj').read_text(encoding='utf-8')
        builder = (root / 'scripts/build-windows-preview.ps1').read_text(encoding='utf-8')
        self.assertIn('FamilyActivityBundle.zip', project)
        self.assertIn('Path.IsPathRooted(relative)', source)
        self.assertIn('part is "" or "." or ".."', source)
        self.assertIn('MaxExpandedBytes', source)
        self.assertIn('FamilyActivitySetup.exe', source)
        self.assertIn('FamilyActivityCore/FamilyActivityCore.exe', source)
        self.assertIn('Monitoring will not start until the next screen', installer)
        self.assertIn('TryCreateShortcut(target)', installer)
        self.assertIn('Open Family Activity setup and parent dashboard', installer)
        self.assertIn('file and folder at the same path', source)
        self.assertIn('outside its install folder', source)
        self.assertIn('FamilyActivityInstaller.exe', builder)
        self.assertIn('--self-test', builder)

    def test_collection_disclosure_is_scrollable_and_separate_from_acknowledgment(self):
        source = (Path(__file__).parents[1] / 'native/windows/setup/Program.cs').read_text(encoding='utf-8')
        self.assertIn('Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Vertical, WordWrap = true', source)
        self.assertIn('disclosureText.AccessibleName = "Monitoring collection and limits"', source)
        self.assertIn('disclosed.Text = "I have explained this monitoring to the child, and they understand it will run on this account."', source)
        self.assertIn('if (!disclosed.Checked)', source)
        self.assertNotIn('disclosed.Text = "I have explained this monitoring to the child. It samples', source)

    def test_connect_code_field_accepts_only_the_two_digit_selector(self):
        source = (Path(__file__).parents[1] / 'native/windows/setup/Program.cs').read_text(encoding='utf-8')
        self.assertIn('MaxLength = 2', source)
        self.assertIn('char.IsAsciiDigit(e.KeyChar)', source)
        self.assertIn("typedCode.Length != 2", source)
        self.assertIn('connection file instead', source)
        self.assertIn('Choose connection file…', source)
        self.assertIn('Choose the connection file from your parent', source)
        self.assertNotIn('Choose public-key file', source)
        self.assertNotIn("parent's public key", source)
        self.assertIn('Reports are locked on this computer and can be opened on the parent\'s computer', source)

    def test_windows_package_has_noninteractive_setup_and_removal_ui_self_check(self):
        root = Path(__file__).parents[1]
        source = (root / 'native/windows/setup/Program.cs').read_text(encoding='utf-8')
        tray = (root / 'native/windows/Program.cs').read_text(encoding='utf-8')
        entry = (root / 'native/windows/SetupEntry.cs').read_text(encoding='utf-8')
        builder = (root / 'scripts/build-windows-preview.ps1').read_text(encoding='utf-8')
        self.assertIn('RunUiSelfTest()', source)
        self.assertIn('SelfTestProgramRemoval()', source)
        self.assertIn('ScheduleProgramRemoval(folder)', source)
        self.assertEqual(source.count('private static bool ScheduleProgramRemoval(string folder)'), 1)
        self.assertLess(source.index('private static bool ScheduleProgramRemoval(string folder)'),
                        source.index('private sealed class SetupForm'))
        self.assertIn('ScheduleProgramRemoval(sourceFolder)', source)
        self.assertIn('deferred Windows program-folder cleanup did not finish', source)
        self.assertIn('FileShare.None', source)
        self.assertIn('did not wait for a locked program file', source)
        self.assertIn("Two digits from the parent's dashboard", source)
        self.assertIn('ScrollBars.Vertical', source)
        self.assertIn('It does not record resolver addresses', source)
        self.assertIn('retention.SelectedIndex != 1', source)
        self.assertIn('This is the maximum time to keep detailed records here', source)
        self.assertIn('calendar-day rounding may remove them up to a day before that limit', source)
        self.assertIn('retention.Items.Count != 5', source)
        self.assertIn('deleteData is null || deleteData.Checked', source)
        self.assertIn('Family Activity settings', source)
        self.assertIn('--self-test-ui', entry)
        self.assertIn('FamilyActivitySyntheticForeground.exe', entry)
        self.assertIn('Synthetic Study App', entry)
        self.assertIn('TrayCompanion.RunStatusSelfTest()', entry)
        self.assertIn('--self-test-status-ipc', entry)
        self.assertIn('--self-test-ui', builder)
        self.assertIn('validate-windows-install-flow.py', builder)
        self.assertIn('tray state self-check failed', builder)
        self.assertIn('A setup record is present. Do not run setup again', source)
        self.assertIn('install.Enabled = !taskMayBeRegistered', source)
        self.assertIn('Monitoring has started and its visible status indicator is ready', source)
        self.assertIn('then it should say ‘Monitoring is on’', source)
        self.assertIn('heartbeatSignal.WaitOne(0)', tray)
        self.assertIn('ResolveState(TimeSpan.FromSeconds(46), null, timeout)', tray)
        self.assertIn('ResolveState(TimeSpan.FromSeconds(30), TimeSpan.FromSeconds(10), timeout)', tray)
        self.assertIn('new EventWaitHandle(false, EventResetMode.AutoReset, heartbeatName)', tray)
        self.assertIn('AccessibleDescription = "Waiting for the first completed encrypted sample."', tray)
        self.assertIn('No recent completed sample was received. The reason is unknown', tray)
        self.assertIn('RunHeartbeatIpcSelfTest()', tray)
        self.assertIn('Monitoring is starting', tray)
        self.assertIn('Monitoring is on', tray)
        self.assertIn('Monitoring is paused', tray)

    def test_live_windows_task_validator_uses_only_synthetic_activity(self):
        root = Path(__file__).parents[1]
        validator = (root / 'scripts/validate-windows-install-flow.py').read_text(encoding='utf-8')
        builder = (root / 'scripts/build-windows-preview.ps1').read_text(encoding='utf-8')
        self.assertIn('FamilyActivitySyntheticForeground.exe', validator)
        self.assertIn('monitor_network=False', validator)
        self.assertIn('inspect_network_settings=False', validator)
        self.assertIn('process.kill()', validator)
        self.assertIn('require_gap=True', validator)
        self.assertIn('windows_install.uninstall(profile)', validator)
        self.assertIn('preserve temporary data', validator)
        self.assertIn('validate-windows-install-flow.py', builder)

    def test_windows_setup_requests_immediate_start_and_validator_does_not_start_twice(self):
        root = Path(__file__).parents[1]
        installer = (root / 'family_activity/windows_install.py').read_text(encoding='utf-8')
        validator = (root / 'scripts/validate-windows-install-flow.py').read_text(encoding='utf-8')
        guide = (root / 'WINDOWS.md').read_text(encoding='utf-8')
        self.assertIn("runner([str(task_path), '/Run', '/TN', TASK_NAME])", installer)
        self.assertIn('_wait_for_ready_session(database, previous_event_count)', installer)
        self.assertIn('visible status indicator is ready', (root / 'native/windows/setup/Program.cs').read_text(encoding='utf-8'))
        self.assertLess(installer.index('registration_uncertain = True', installer.index("'/Create'")),
                        installer.index("'/Run'"))
        self.assertIn('windows_install.install(', validator)
        self.assertNotIn("_run_task('/Run'", validator)
        self.assertIn('start the agent immediately', guide)
        self.assertIn('tray and an encrypted session to become ready', guide)
        self.assertIn('same task runs at later sign-ins', guide)
        self.assertIn('verifies a live encrypted', validator)
        self.assertIn('visible status companion is ready', (root / 'family_activity/__main__.py').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
