import unittest
from pathlib import Path


class MacSetupSourceTests(unittest.TestCase):
    def test_welcome_screen_separates_release_status_privacy_and_next_actions(self):
        source = (Path(__file__).parents[1] / 'native' / 'macos' / 'setup.swift').read_text()
        launch = source[source.index('func applicationDidFinishLaunching'):source.index('private func showWelcomeWindow')]
        welcome = source[source.index('private func showWelcomeWindow'):source.index('@objc private func openDashboardFromWelcome')]

        self.assertIn('showWelcomeWindow()', launch)
        self.assertNotIn('runModal()', welcome)
        self.assertIn('This version is not ready for everyday family use', welcome)
        self.assertIn('What this preview records', welcome)
        self.assertIn('What it never records', welcome)
        self.assertIn('Network bytes are not attributed to apps or websites', welcome)
        self.assertIn('Open parent dashboard', welcome)
        self.assertIn('Set up this Mac together…', welcome)
        self.assertIn('More options…', welcome)

    def test_status_menu_does_not_claim_the_unintegrated_browser_add_on_collects(self):
        source = (Path(__file__).parents[1] / 'native' / 'macos' / 'status.swift').read_text()
        details = source[source.index('private func showDetails'):source.index('// Choose a local IPv4 address')]

        self.assertIn('Website domains are not part of this Mac setup', details)
        self.assertIn('the experimental browser add-on is separate and is not connected here', details)
        self.assertNotIn('active website domains when the optional browser extension is enabled', details)

    def test_install_dialog_explains_retention_is_a_maximum_with_day_rounding(self):
        source = (Path(__file__).parents[1] / 'native' / 'macos' / 'setup.swift').read_text(encoding='utf-8')
        self.assertIn('Choose the maximum time to keep detailed records', source)
        self.assertIn('calendar-day rounding may remove them up to a day before that limit', source)

    def test_parent_pairing_calls_fallback_a_connection_file(self):
        source = (Path(__file__).parents[1] / 'native' / 'macos' / 'setup.swift').read_text(encoding='utf-8')
        self.assertIn('Choose connection file…', source)
        self.assertIn('Choose the connection file from your parent', source)
        self.assertIn('Do not select the encrypted recovery copy', source)
        self.assertIn("That doesn't look like a Family Activity connection file", source)

    def test_mac_child_disclosure_explains_reports_without_key_terms(self):
        root = Path(__file__).parents[1]
        setup = (root / 'native' / 'macos' / 'setup.swift').read_text(encoding='utf-8')
        status = (root / 'native' / 'macos' / 'status.swift').read_text(encoding='utf-8')
        self.assertIn("Reports are locked on this Mac and can be opened on the parent's computer", setup)
        self.assertIn("Reports are locked on this Mac and can be opened on the parent's computer", status)
        self.assertNotIn("Activity is encrypted to the parent's key", setup)
        self.assertNotIn('Reports are encrypted to a key held by the parent', status)

    def test_parent_key_pairing_is_cancelable_and_reads_off_the_ui_thread(self):
        source = (Path(__file__).parents[1] / 'native' / 'macos' / 'setup.swift').read_text()
        start = source.index('private func fetchParentKey()')
        end = source.index('private func reviewAndInstall', start)
        pairing = source[start:end]

        background_reader = pairing.index('DispatchQueue.global(qos: .userInitiated).async')
        self.assertLess(background_reader, pairing.index('output.fileHandleForReading.readDataToEndOfFile()'))
        self.assertLess(background_reader, pairing.index('process.waitUntilExit()'))
        self.assertIn('NSProgressIndicator', pairing)
        self.assertIn('progress.setAccessibilityLabel("Connecting to the parent\'s Mac")', pairing)
        self.assertIn('waiting.addButton(withTitle: "Cancel")', pairing)
        self.assertIn('code.utf8.count == 2', pairing)
        self.assertIn('Enter the two digits shown in the parent\'s dashboard', pairing)
        self.assertIn('ask them to create another', pairing)
        self.assertIn('if response == .alertFirstButtonReturn', pairing)
        self.assertIn('pairingProcess?.terminate()', pairing)
        self.assertIn('stopModal(withCode: .continue)', pairing)

    def test_install_and_removal_progress_drain_subprocess_output_off_ui_thread(self):
        source = (Path(__file__).parents[1] / 'native' / 'macos' / 'setup.swift').read_text()
        runner = source[source.index('private func runWithProgress'):source.index('private func failureText')]
        self.assertIn('runWithProgress(arguments, title: "Setting up this Mac…"', source)
        self.assertIn('runWithProgress(arguments, title: "Removing Family Activity…"', source)
        self.assertIn('reviewAndInstall(key, temporaryDirectory: temporaryDirectory)', source)
        self.assertIn('if let temporaryDirectory { try? FileManager.default.removeItem(at: temporaryDirectory) }', source)
        background = runner.index('DispatchQueue.global(qos: .userInitiated).async')
        self.assertLess(background, runner.index('errors.fileHandleForReading.readDataToEndOfFile()'))
        self.assertLess(background, runner.index('process.waitUntilExit()'))
        self.assertIn('process.waitUntilExit()', runner)
        self.assertIn('operationWindow?.close()', runner)
        self.assertIn('func applicationShouldTerminate(_ sender: NSApplication)', source)
        self.assertIn('return .terminateCancel', source)


if __name__ == '__main__':
    unittest.main()
