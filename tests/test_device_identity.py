import os
from pathlib import Path
import tempfile
import unittest

from family_activity import device_identity


class DeviceIdentityTests(unittest.TestCase):
    def test_identity_is_stable_random_and_private_to_its_database(self):
        with tempfile.TemporaryDirectory() as folder:
            first_database = Path(folder) / 'first.sqlite3'
            second_database = Path(folder) / 'second.sqlite3'
            first = device_identity.load_or_create(first_database)
            self.assertEqual(device_identity.load_or_create(first_database), first)
            self.assertNotEqual(device_identity.load_or_create(second_database), first)
            self.assertRegex(first, r'^[0-9a-f]{32}$')
            identity_file = device_identity.identity_path(first_database)
            self.assertEqual(identity_file.read_text('ascii'), first + '\n')
            if os.name == 'posix':
                self.assertEqual(identity_file.stat().st_mode & 0o777, 0o600)

    def test_rejects_invalid_or_redirected_identity_files(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / 'activity.sqlite3'
            identity_file = device_identity.identity_path(database)
            identity_file.write_text('not-an-id\n', encoding='ascii')
            with self.assertRaisesRegex(ValueError, 'invalid'):
                device_identity.load_or_create(database)
            identity_file.unlink()
            target = Path(folder) / 'target'
            target.write_text('a' * 32 + '\n', encoding='ascii')
            try:
                identity_file.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest('symbolic links are unavailable')
            with self.assertRaisesRegex(ValueError, 'regular file'):
                device_identity.load_or_create(database)
