import sqlite3
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone

from nacl.public import PrivateKey

from family_activity import device_labels, encrypted_store, encrypted_view
from family_activity.encrypted_agent_store import EncryptedAgentStore
from family_activity.local_share import encrypted_snapshot


class DeviceLabelTests(unittest.TestCase):
    def test_parent_names_are_encrypted_report_events_and_survive_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'report.sqlite3'
            key = PrivateKey.generate()
            identifier = 'a' * 32
            writer = EncryptedAgentStore(path, key.public_key, 30)
            writer.event('start')
            writer.event('stop')
            writer.close()

            device_labels.set_label(path, key, identifier, "Annika's Mac")
            # The child has the parent's public key and can seal events, but
            # it cannot create an authenticated parent rename.
            forged = encrypted_store.seal_event(key.public_key, {
                'type': 'device_label',
                'at': datetime.now(timezone.utc).isoformat(timespec='microseconds'),
                'target_device_id': 'b' * 32,
                'label': 'Child forged name',
            })
            with sqlite3.connect(path) as database:
                authentic_ciphertext = database.execute(
                    'SELECT ciphertext FROM encrypted_events ORDER BY id DESC LIMIT 1').fetchone()[0]
            replayed = encrypted_store.open_event(key, authentic_ciphertext)
            replayed['label'] = 'Tampered parent name'
            tampered = encrypted_store.seal_event(key.public_key, replayed)
            expiry = (datetime.now(timezone.utc).date() + timedelta(days=30)).isoformat()
            with sqlite3.connect(path) as database:
                database.execute('INSERT INTO encrypted_events(expires_on,ciphertext) VALUES (?,?)',
                                 (expiry, forged))
                database.execute('INSERT INTO encrypted_events(expires_on,ciphertext) VALUES (?,?)',
                                 (expiry, tampered))
            stored = path.read_bytes()
            self.assertNotIn(b"Annika's Mac", stored)
            with sqlite3.connect(path) as database:
                self.assertEqual({row[0] for row in database.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")},
                    {'key_commitment', 'encrypted_events'})
            projected, incomplete = encrypted_view.open_projection(path, key)
            try:
                self.assertFalse(incomplete)
                self.assertEqual(projected.execute(
                    'SELECT device_id, label FROM device_labels').fetchall(),
                    [(identifier, "Annika's Mac")])
            finally:
                projected.close()

            backup = encrypted_snapshot(path)
            restored, _ = encrypted_view.open_projection_bytes(backup, key)
            try:
                self.assertEqual(restored.execute(
                    'SELECT device_id, label FROM device_labels').fetchall(),
                    [(identifier, "Annika's Mac")])
            finally:
                restored.close()
            with self.assertRaises(Exception):
                encrypted_view.open_projection_bytes(backup, PrivateKey.generate())

    def test_newer_name_wins_and_invalid_names_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'report.sqlite3'
            key = PrivateKey.generate()
            writer = EncryptedAgentStore(path, key.public_key, 30)
            writer.event('start')
            writer.close()
            identifier = 'f' * 32
            device_labels.set_label(path, key, identifier, 'First name')
            device_labels.set_label(path, key, identifier, 'Updated name')
            projected, _ = encrypted_view.open_projection(path, key)
            try:
                self.assertEqual(projected.execute(
                    'SELECT label FROM device_labels WHERE device_id=?', (identifier,)).fetchone(),
                    ('Updated name',))
            finally:
                projected.close()
            for invalid_id, invalid_label in (("../outside", 'Laptop'),
                                               ('legacy', '   '),
                                               ('legacy', 'x' * 49),
                                               ('legacy', 'child\nname')):
                with self.subTest(identifier=invalid_id, label=invalid_label):
                    with self.assertRaises(ValueError):
                        device_labels.set_label(path, key, invalid_id, invalid_label)


if __name__ == '__main__':
    unittest.main()
