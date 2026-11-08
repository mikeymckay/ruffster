import os
from pathlib import Path
import tempfile
import unittest
from family_activity.parent_settings import (DEFAULT_RETENTION_DAYS, RETENTION_OPTIONS,
                                              load_backup_confirmation, load_retention,
                                              save_backup_confirmation, save_retention,
                                              validate_retention_days)


class ParentSettingsTests(unittest.TestCase):
    def test_default_and_atomic_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'preferences.json'
            self.assertEqual(load_retention(path), DEFAULT_RETENTION_DAYS)
            save_retention(path, 90)
            self.assertEqual(load_retention(path), 90)
            self.assertEqual(list(Path(tmp).iterdir()), [path])
            if os.name == 'posix':
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_corrupt_or_unknown_preferences_fall_back_to_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'preferences.json'
            path.write_text('{broken')
            self.assertEqual(load_retention(path), DEFAULT_RETENTION_DAYS)
            path.write_text('{"retention_days": 14}')
            self.assertEqual(load_retention(path), DEFAULT_RETENTION_DAYS)

    def test_only_supported_integer_options_are_accepted(self):
        for option in RETENTION_OPTIONS:
            self.assertEqual(validate_retention_days(option), option)
        for invalid in (True, 0, 14, 999, '30', None):
            with self.assertRaises(ValueError): validate_retention_days(invalid)

    def test_backup_confirmation_persists_and_survives_retention_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'parent-settings.json'
            self.assertFalse(load_backup_confirmation(path))
            save_backup_confirmation(path, True)
            self.assertTrue(load_backup_confirmation(path))
            save_retention(path, 90)
            self.assertEqual(load_retention(path), 90)
            self.assertTrue(load_backup_confirmation(path))
            save_backup_confirmation(path, False)
            self.assertFalse(load_backup_confirmation(path))

    def test_legacy_retention_settings_default_backup_confirmation_to_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'parent-settings.json'
            path.write_text('{"retention_days":90}')
            self.assertEqual(load_retention(path), 90)
            self.assertFalse(load_backup_confirmation(path))

    def test_backup_confirmation_must_be_boolean(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'parent-settings.json'
            with self.assertRaises(ValueError):
                save_backup_confirmation(path, 1)


if __name__ == '__main__':
    unittest.main()
