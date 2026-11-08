import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from nacl.exceptions import CryptoError
from nacl.public import PrivateKey
from family_activity import encrypted_store as secure


class EncryptionTests(unittest.TestCase):
    def test_public_key_writes_parent_key_reads_and_wrong_key_fails(self):
        parent = PrivateKey.generate()
        other = PrivateKey.generate()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'events.db'
            db = secure.connect(path)
            event = {'app': 'UNIQUE_PRIVATE_APP_918273', 'time': '2026-11-07T09:30:00Z'}
            secure.append(db, parent.public_key, event)
            self.assertEqual(list(secure.read(db, parent)), [event])
            with self.assertRaises(CryptoError):
                list(secure.read(db, other))
            db.close()
            for filename in Path(tmp).iterdir():
                data = filename.read_bytes()
                self.assertNotIn(b'UNIQUE_PRIVATE_APP_918273', data)
                self.assertNotIn(b'2026-11-07T09:30:00Z', data)
            if os.name == 'posix':
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_tamper_and_record_size(self):
        parent = PrivateKey.generate()
        first = secure.seal_event(parent.public_key, {'x': 'short'})
        second = secure.seal_event(parent.public_key, {'x': 'a much longer value'})
        self.assertEqual(len(first), len(second))
        damaged = bytearray(first)
        damaged[-1] ^= 1
        with self.assertRaises(CryptoError):
            secure.open_event(parent, bytes(damaged))
        with self.assertRaises(ValueError):
            secure.seal_event(parent.public_key, {'too_big': 'x' * 5000})

    def test_public_key_cannot_decrypt(self):
        parent = PrivateKey.generate()
        encrypted = secure.seal_event(parent.public_key, {'x': 1})
        with self.assertRaises(TypeError):
            secure.open_event(parent.public_key, encrypted)

    def test_legacy_4096_byte_event_and_new_size_buckets(self):
        import json
        import struct
        from nacl.public import SealedBox
        parent = PrivateKey.generate()
        event = {'type':'heartbeat', 'session':'legacy', 'at':'2026-11-07T00:00:00+00:00'}
        data = json.dumps({'version':1, 'event':event},separators=(',',':')).encode()
        legacy = struct.pack('>I',len(data)) + data + bytes(4096 - len(data) - 4)
        encrypted = SealedBox(parent.public_key).encrypt(legacy)
        self.assertEqual(secure.open_event(parent, encrypted), event)
        small = secure.seal_event(parent.public_key, event)
        larger = secure.seal_event(parent.public_key, {'value':'x'*800})
        self.assertLess(len(small), len(encrypted))
        self.assertGreater(len(larger), len(small))
        self.assertEqual(secure.open_event(parent, larger)['value'], 'x'*800)
