import os
from pathlib import Path
import plistlib
import stat
import subprocess
import sys
from types import SimpleNamespace
import tempfile
import unittest
from nacl.public import PrivateKey
from family_activity.macos_install import install, uninstall

class FakeLaunchctl:
    def __init__(self, fail_bootstrap=False, fail_bootout=False):
        self.loaded = False; self.fail_bootstrap = fail_bootstrap; self.fail_bootout = fail_bootout
    def __call__(self, args):
        action = args[1]
        if action == 'print': return SimpleNamespace(returncode=0 if self.loaded else 1)
        if action == 'bootstrap':
            if self.fail_bootstrap: return SimpleNamespace(returncode=1)
            self.loaded = True; return SimpleNamespace(returncode=0)
        if action == 'bootout':
            if self.fail_bootout: return SimpleNamespace(returncode=1)
            self.loaded = False; return SimpleNamespace(returncode=0)
        raise AssertionError(args)

class MacInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.home=self.root/'home'; self.home.mkdir()
        self.key=self.root/'parent.pub'; self.key.write_bytes(bytes(PrivateKey.generate().public_key))
        self.source=self.root/'source'; (self.source/'family_activity').mkdir(parents=True); (self.source/'family_activity'/'__main__.py').write_text('')
        self.exe=self.root/'executable'; self.exe.write_text('#!/bin/sh\n'); self.exe.chmod(0o700)
        self.launch=FakeLaunchctl()
    def tearDown(self): self.tmp.cleanup()
    def perform(self, launch=None):
        return install(self.key,self.exe,self.source,self.exe,self.exe,self.home,123,runner=launch or self.launch)

    def test_install_uninstall_retain_data_and_reinstall(self):
        result=self.perform(); self.assertTrue(self.launch.loaded)
        data=Path(result['data_directory'])
        from family_activity.encrypted_agent_store import EncryptedAgentStore
        from nacl.public import PublicKey
        encrypted=EncryptedAgentStore(data/'activity.sqlite3',PublicKey(self.key.read_bytes()),30)
        encrypted.event('start'); encrypted.close()
        original=(data/'activity.sqlite3').read_bytes()
        with self.assertRaises(FileExistsError): self.perform()
        removed=uninstall(self.home,123,runner=self.launch)
        self.assertFalse(self.launch.loaded); self.assertTrue(removed['database_exists'])
        self.assertEqual((data/'activity.sqlite3').read_bytes(),original)
        network_key = (data / 'network.key').read_bytes()
        self.assertEqual(len(network_key), 32)
        self.perform(); self.assertTrue(self.launch.loaded)
        self.assertEqual((data / 'network.key').read_bytes(), network_key)

    def test_installed_agent_receives_private_device_network_key(self):
        result = self.perform()
        data = Path(result['data_directory'])
        network_key = data / 'network.key'
        self.assertEqual(len(network_key.read_bytes()), 32)
        self.assertEqual(stat.S_IMODE(network_key.stat().st_mode), 0o600)
        arguments = plistlib.loads(Path(result['plist']).read_bytes())['ProgramArguments']
        self.assertEqual(arguments[arguments.index('--experimental-network-key') + 1], str(network_key))

    def test_explicit_delete_data_removes_only_known_local_files(self):
        result = self.perform()
        data = Path(result['data_directory'])
        for suffix in ('-wal', '-shm', '-journal', '.lock'):
            (data / ('activity.sqlite3' + suffix)).write_text('sidecar')
        unrelated = data / 'notes.txt'; unrelated.write_text('leave this alone')
        removed = uninstall(self.home, 123, runner=self.launch, delete_data=True)
        self.assertTrue(removed['data_deleted'])
        self.assertFalse((data / 'parent.pub').exists())
        self.assertFalse((data / 'network.key').exists())
        self.assertFalse((data / 'activity.sqlite3').exists())
        self.assertFalse((data / 'install.json').exists())
        for suffix in ('-wal', '-shm', '-journal', '.lock'):
            self.assertFalse((data / ('activity.sqlite3' + suffix)).exists())
        self.assertEqual(unrelated.read_text(), 'leave this alone')

    def test_failure_rolls_back_new_files(self):
        with self.assertRaises(RuntimeError): self.perform(FakeLaunchctl(fail_bootstrap=True))
        data=self.home/'Library'/'Application Support'/'Family Activity'
        self.assertFalse((data/'parent.pub').exists()); self.assertFalse((data/'install.json').exists())
        self.assertFalse((data/'network.key').exists())

    def test_refuses_invalid_existing_network_key(self):
        data = self.home/'Library'/'Application Support'/'Family Activity'
        data.mkdir(parents=True)
        (data/'network.key').write_bytes(b'too short')
        with self.assertRaisesRegex(ValueError, 'network identifier key is invalid'):
            self.perform()
        self.assertFalse(self.launch.loaded)
        self.assertEqual((data/'network.key').read_bytes(), b'too short')

    def test_install_uses_selected_retention(self):
        result=install(self.key,self.exe,self.source,self.exe,self.exe,self.home,123,
                       runner=self.launch,retention_days=7)
        import plistlib
        args=plistlib.loads(Path(result['plist']).read_bytes())['ProgramArguments']
        self.assertEqual(args[args.index('--retention-days')+1],'7')

    def test_packaged_launch_agent_is_associated_with_its_host_app(self):
        bundle_contents = self.root / 'Family Activity.app' / 'Contents'
        runtime = bundle_contents / 'Resources' / 'runtime'
        package = runtime / 'family_activity'
        package.mkdir(parents=True)
        (package / '__main__.py').write_text('')
        (bundle_contents / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'org.example.family'}))
        result = install(self.key, self.exe, runtime, self.exe, self.exe, self.home, 123,
                         runner=self.launch)
        definition = plistlib.loads(Path(result['plist']).read_bytes())
        self.assertEqual(definition['AssociatedBundleIdentifiers'], ['org.example.family'])

    def test_installer_supports_synthetic_only_collection_validation(self):
        result = install(self.key, self.exe, self.source, self.exe, self.exe, self.home, 123,
                         runner=self.launch, collect_network=False,
                         collect_network_settings=False)
        arguments = plistlib.loads(Path(result['plist']).read_bytes())['ProgramArguments']
        self.assertNotIn('--experimental-network', arguments)
        self.assertNotIn('--experimental-network-settings', arguments)

    def test_live_mac_agent_validation_is_documented(self):
        guide = (Path(__file__).resolve().parents[1] / 'MACOS-DISTRIBUTION.md').read_text(encoding='utf-8')
        self.assertIn('python scripts/validate-macos-agent-runtime.py', guide)
        self.assertIn('network collection disabled', guide)
        self.assertIn('preserves the synthetic fixture directory', guide)

    def test_live_agent_validator_handles_uncertain_launchd_cleanup(self):
        validator = (Path(__file__).resolve().parents[1] / 'scripts' /
                     'validate-macos-agent-runtime.py').read_text(encoding='utf-8')
        self.assertIn('def _service_present(domain, label):', validator)
        self.assertIn("_launchctl('bootout', f'{domain}/{label}')", validator)
        self.assertIn('folder.rename(preserved)', validator)
        self.assertIn('AssociatedBundleIdentifiers', validator)
        self.assertIn('synthetic host app bundle', validator)

    def test_refuses_modified_definition_and_failed_stop(self):
        result=self.perform(); plist=Path(result['plist']); original=plist.read_bytes(); plist.write_bytes(original+b' ')
        with self.assertRaises(ValueError): uninstall(self.home,123,runner=self.launch)
        plist.write_bytes(original); self.launch.fail_bootout=True
        with self.assertRaises(RuntimeError): uninstall(self.home,123,runner=self.launch)
        self.assertTrue(plist.exists())

    def test_uninstall_rejects_path_traversal_and_preserves_files(self):
        with self.assertRaises(ValueError):
            uninstall(self.home,123,label='../../outside',runner=self.launch)
        self.assertTrue(self.home.exists())

    def test_uninstall_refuses_symlinked_data_directory_before_stopping_or_deleting(self):
        result = self.perform()
        data = Path(result['data_directory'])
        outside = self.root / 'outside-data'
        outside.mkdir()
        (outside / 'parent.pub').write_bytes((data / 'parent.pub').read_bytes())
        (outside / 'network.key').write_bytes((data / 'network.key').read_bytes())
        (outside / 'activity.sqlite3').write_bytes(b'preserve external file')
        (outside / 'install.json').write_bytes((data / 'install.json').read_bytes())
        original = self.root / 'original-data'
        data.rename(original)
        data.symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, 'symbolic links'):
            uninstall(self.home, 123, runner=self.launch, delete_data=True)

        self.assertTrue(self.launch.loaded)
        self.assertTrue((outside / 'parent.pub').is_file())
        self.assertTrue((outside / 'network.key').is_file())
        self.assertEqual((outside / 'activity.sqlite3').read_bytes(), b'preserve external file')
        self.assertTrue(Path(result['plist']).is_file())

    def test_uninstall_checks_data_symlinks_before_stopping_agent(self):
        result = self.perform()
        data = Path(result['data_directory'])
        outside = self.root / 'outside-sidecar'
        outside.write_text('preserve external file')
        (data / 'activity.sqlite3-wal').symlink_to(outside)

        with self.assertRaisesRegex(ValueError, 'symbolic link'):
            uninstall(self.home, 123, runner=self.launch, delete_data=True)

        self.assertTrue(self.launch.loaded)
        self.assertTrue(Path(result['plist']).is_file())
        self.assertTrue((data / 'install.json').is_file())
        self.assertTrue((data / 'parent.pub').is_file())
        self.assertEqual(outside.read_text(), 'preserve external file')

    def test_existing_plaintext_database_is_not_reused(self):
        data=self.home/'Library'/'Application Support'/'Family Activity'
        data.mkdir(mode=0o700,parents=True)
        (data/'parent.pub').write_bytes(self.key.read_bytes())
        import sqlite3
        db=sqlite3.connect(data/'activity.sqlite3'); db.execute('CREATE TABLE sensitive(value TEXT)'); db.commit(); db.close()
        with self.assertRaises(ValueError): self.perform()
        self.assertFalse(self.launch.loaded)
        self.assertTrue((data/'activity.sqlite3').exists())

    def test_mac_install_cli_reports_actionable_error_without_traceback(self):
        missing_key = self.root / 'missing-parent.pub'
        bootstrap = "import sys; sys.platform='darwin'; from family_activity.__main__ import main; main()"
        result = subprocess.run([sys.executable, '-c', bootstrap, 'mac-install',
                                 '--public-key', str(missing_key),
                                 '--source-directory', str(self.source),
                                 '--foreground-helper', str(self.exe),
                                 '--status-helper', str(self.exe), '--disclosed'],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertIn('No such file', result.stderr)
        self.assertNotIn('Traceback', result.stderr)
