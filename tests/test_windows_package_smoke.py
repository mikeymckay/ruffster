import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    'validate_windows_preview_bundle', ROOT / 'scripts/validate-windows-preview-bundle.py')
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class WindowsPackageSmokeTests(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'the synthetic shebang executable is Unix-only; CI validates the real Windows package')
    def test_validator_checks_local_dashboard_with_an_executable_core(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary)
            core_folder = package / 'FamilyActivityCore'
            core_folder.mkdir()
            setup = package / 'FamilyActivitySetup.exe'
            setup.write_bytes(b'GUI executable placeholder')
            core = core_folder / 'FamilyActivityCore.exe'
            core.write_text(
                '#!' + sys.executable + '\n'
                'import sys\n'
                f'sys.path.insert(0, {str(ROOT)!r})\n'
                'from family_activity.__main__ import main\n'
                'main()\n',
                encoding='utf-8')
            core.chmod(0o755)

            result = VALIDATOR.validate(package)

        self.assertIn('loopback dashboard', result)
        self.assertIn('unauthenticated API rejection', result)
        self.assertIn('frozen encrypted file export/import and IANA schedule/report checks passed (Europe/Vienna)', result)
        self.assertIn('Windows named-event check skipped on this host.', result)

    def test_windows_builder_bundles_iana_timezone_data(self):
        builder = (ROOT / 'scripts' / 'build-windows-preview.ps1').read_text(encoding='utf-8')
        project = (ROOT / 'pyproject.toml').read_text(encoding='utf-8')
        self.assertIn('--collect-all tzdata', builder)
        self.assertIn('tzdata>=2025.1; sys_platform == \'win32\'', project)

    def test_validator_rejects_incomplete_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(RuntimeError, 'missing its setup executable or frozen core'):
                VALIDATOR.validate(temporary)


if __name__ == '__main__':
    unittest.main()
