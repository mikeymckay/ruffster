import unittest
from pathlib import Path


class MacSetupSourceTests(unittest.TestCase):
    def test_packaged_setup_checks_welcome_layout_without_showing_it(self):
        root = Path(__file__).parents[1]
        source = (root / 'native' / 'macos' / 'setup.swift').read_text(encoding='utf-8')
        builder = (root / 'scripts' / 'build-macos-preview.sh').read_text(encoding='utf-8')
        self.assertIn('func runWelcomeLayoutSelfTest()', source)
        self.assertIn('showWelcomeWindow(visible: false)', source)
        self.assertIn('stack.fittingSize', source)
        self.assertIn('Set up this Mac together…', source)
        self.assertIn('"--self-test-ui"', source)
        self.assertIn('"$APP/Contents/MacOS/FamilyActivitySetup" --self-test-ui', builder)

    def test_mac_release_bundle_uses_its_release_tag_as_the_bundle_version(self):
        root = Path(__file__).parents[1]
        builder = (root / 'scripts' / 'build-macos-preview.sh').read_text(encoding='utf-8')
        workflow = (root / '.github' / 'workflows' / 'release-macos-unsigned-preview.yml').read_text(encoding='utf-8')
        self.assertIn('VERSION=${RUFFSTER_VERSION:-0.1.5}', builder)
        self.assertIn("'CFBundleShortVersionString':sys.argv[2]", builder)
        self.assertIn("'CFBundleVersion':sys.argv[2]", builder)
        self.assertIn('export RUFFSTER_VERSION="${GITHUB_REF_NAME#mac-preview-}"', workflow)

    def test_status_menu_can_save_encrypted_report_for_offline_transfer(self):
        source = (Path(__file__).parents[1] / 'native' / 'macos' / 'status.swift').read_text()
        self.assertIn('Save an encrypted report file…', source)
        self.assertIn('This option does not use the local network.', source)
        self.assertIn('export-report', source)
        self.assertIn('showExportProgressWindow()', source)
        self.assertIn('Open a report file instead', source)

    def test_welcome_screen_separates_release_status_privacy_and_next_actions(self):
        source = (Path(__file__).parents[1] / 'native' / 'macos' / 'setup.swift').read_text()
        launch = source[source.index('func applicationDidFinishLaunching'):source.index('private func showWelcomeWindow')]
        welcome = source[source.index('private func showWelcomeWindow'):source.index('@objc private func openDashboardFromWelcome')]

        self.assertIn('showWelcomeWindow()', launch)
        self.assertNotIn('runModal()', welcome)
        self.assertIn('Ruffster helps parents and children understand computer use', welcome)
        self.assertIn('Choose the parent dashboard on your computer', welcome)
        self.assertIn('What Ruffster records', welcome)
        self.assertIn('What stays private', welcome)
        self.assertIn('Network traffic totals do not identify websites', welcome)
        self.assertIn('Open parent dashboard', welcome)
        self.assertIn('Set up this Mac together…', welcome)
        self.assertIn('More options…', welcome)

    def test_status_menu_does_not_claim_the_unintegrated_browser_add_on_collects(self):
        source = (Path(__file__).parents[1] / 'native' / 'macos' / 'status.swift').read_text()
        details = source[source.index('private func showDetails'):source.index('// Choose a local IPv4 address')]

        self.assertIn('alert.messageText = "About Ruffster"', details)
        self.assertIn('Ruffster helps your family understand computer use', details)
        self.assertIn('some time may be missing from the report; let your parent know', details)
        self.assertNotIn('experimental monitoring', details)
        self.assertNotIn('this test', details)
        self.assertIn('Website domains are not part of this Mac setup', details)
        self.assertIn('a separate experimental browser add-on is not connected to this report', details)
        self.assertNotIn('active website domains when the optional browser extension is enabled', details)

    def test_install_dialog_explains_retention_is_a_maximum_with_day_rounding(self):
        source = (Path(__file__).parents[1] / 'native' / 'macos' / 'setup.swift').read_text(encoding='utf-8')
        self.assertIn('Choose the maximum time to keep detailed records', source)
        self.assertIn('calendar-day rounding may remove them up to a day before that limit', source)

    def test_process_traffic_is_off_by_default_and_disclosed(self):
        source = (Path(__file__).parents[1] / 'native' / 'macos' / 'setup.swift').read_text(encoding='utf-8')
        status = (Path(__file__).parents[1] / 'native' / 'macos' / 'status.swift').read_text(encoding='utf-8')
        self.assertIn('processNetwork.state = .off', source)
        self.assertIn('Include network totals by app or service (experimental)', source)
        self.assertIn('helper service', source)
        self.assertIn('does not identify websites', source)
        self.assertIn('FAMILY_ACTIVITY_PROCESS_NETWORK', status)

    def test_scrollable_disclosure_uses_explicit_cgfloat_height(self):
        source = (Path(__file__).parents[1] / 'native' / 'macos' / 'setup.swift').read_text(encoding='utf-8')
        self.assertIn('NSSize(width: 430, height: CGFloat.greatestFiniteMagnitude)', source)

    def test_mac_install_requires_child_acknowledgment_after_scrollable_disclosure(self):
        source = (Path(__file__).parents[1] / 'native' / 'macos' / 'setup.swift').read_text(encoding='utf-8')
        start = source.index('private func reviewAndInstall')
        end = source.index('@objc private func updateSetupConfirmation', start)
        review = source[start:end]
        self.assertIn('review.messageText = "Set up this Mac together?"', review)
        self.assertIn('let disclosureScroll = NSScrollView', review)
        self.assertIn('disclosureScroll.hasVerticalScroller = true', review)
        self.assertIn('message contents, microphone, camera', review)
        self.assertIn('let acknowledgement = NSButton(checkboxWithTitle:', review)
        self.assertIn('I have explained this monitoring to the child', review)
        self.assertIn('let installButton = review.addButton(withTitle: "Install for this account")', review)
        self.assertIn('installConfirmationButton = installButton', review)
        self.assertIn('installConfirmationButton?.isEnabled = false', review)
        self.assertIn('response == .alertFirstButtonReturn, acknowledgement.state == .on', review)

    def test_parent_pairing_calls_fallback_a_connection_file(self):
        source = (Path(__file__).parents[1] / 'native' / 'macos' / 'setup.swift').read_text(encoding='utf-8')
        self.assertIn('Choose connection file…', source)
        self.assertIn('Choose the connection file from your parent', source)
        self.assertIn('Do not select the encrypted recovery copy', source)
        self.assertIn("That doesn't look like a Ruffster connection file", source)

    def test_mac_child_disclosure_explains_reports_without_key_terms(self):
        root = Path(__file__).parents[1]
        setup = (root / 'native' / 'macos' / 'setup.swift').read_text(encoding='utf-8')
        status = (root / 'native' / 'macos' / 'status.swift').read_text(encoding='utf-8')
        self.assertIn("Reports are locked on this Mac and can be opened on the parent's computer", setup)
        self.assertIn("Reports are locked on this Mac and can be opened on your parent's computer", status)
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
        self.assertIn('runWithProgress(arguments, title: "Removing Ruffster…"', source)
        self.assertIn('runWithProgress(arguments, title: "Restarting monitoring…"', source)
        self.assertIn('mac-restart', source)
        self.assertIn('Restart after app update…', source)
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
