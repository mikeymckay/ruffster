import os
from pathlib import Path
import tempfile
import unittest
from nacl.exceptions import CryptoError
from nacl.public import PrivateKey
from family_activity.key_vault import create_new, encrypt_private_key, unlock

class KeyVaultTests(unittest.TestCase):
    def test_key_round_trip_wrong_passphrase_and_corruption(self):
        private = PrivateKey.generate(); password = '638204'
        vault = encrypt_private_key(private, password)
        self.assertNotIn(bytes(private), vault)
        self.assertEqual(bytes(unlock(vault, password)), bytes(private))
        with self.assertRaises(CryptoError): unlock(vault, 'incorrect long password')
        altered = bytearray(vault); altered[-1] ^= 1
        with self.assertRaises(CryptoError): unlock(bytes(altered), password)
        with self.assertRaises(ValueError): unlock(vault[:-1], password)
        with self.assertRaises(ValueError): encrypt_private_key(private, 'not-a-pin')

    def test_older_passphrase_vaults_remain_readable(self):
        from nacl import pwhash, secret, utils
        private = PrivateKey.generate()
        old_phrase = 'older preview recovery phrase'
        salt = utils.random(pwhash.argon2id.SALTBYTES)
        key = pwhash.argon2id.kdf(secret.SecretBox.KEY_SIZE, old_phrase.encode(), salt,
                                  opslimit=3, memlimit=64 * 1024 * 1024)
        old_vault = b'FAMKEY01' + salt + bytes(secret.SecretBox(key).encrypt(bytes(private)))
        self.assertEqual(bytes(unlock(old_vault, old_phrase)), bytes(private))

    def test_parent_access_pin_must_be_six_digits(self):
        private = PrivateKey.generate()
        for pin in ('12345', '1234567', '12ab56', ''):
            with self.subTest(pin=pin), self.assertRaises(ValueError):
                encrypt_private_key(private, pin)

    def test_creation_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'parent.key'
            create_new(path, b'original')
            with self.assertRaises(FileExistsError): create_new(path, b'replacement')
            self.assertEqual(path.read_bytes(), b'original')
            if os.name == 'posix': self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_create_export_and_open_dashboard(self):
        import subprocess
        import sys
        import urllib.request
        from unittest.mock import patch
        from family_activity.__main__ import main
        from family_activity.encrypted_agent_store import EncryptedAgentStore
        from nacl.public import PublicKey
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)/'parent.vault'; pub = Path(tmp)/'parent.pub'; exported = Path(tmp)/'second.pub'
            db = Path(tmp)/'encrypted.db'
            password = '638204'
            with patch('sys.argv', ['family_activity', 'parent-key', 'create', '--vault', str(vault), '--public', str(pub)]), patch('getpass.getpass', side_effect=[password, password]):
                main()
            with patch('sys.argv', ['family_activity', 'parent-key', 'export-public', '--vault', str(vault), '--public', str(exported)]), patch('getpass.getpass', return_value=password):
                main()
            self.assertEqual(pub.read_bytes(), exported.read_bytes())
            writer = EncryptedAgentStore(db, PublicKey(pub.read_bytes()), 30)
            writer.event('start'); writer.event('foreground', application=['TEST_VAULT_APP', 'test']); writer.event('stop'); writer.close()
            proc = subprocess.Popen([sys.executable, '-m', 'family_activity', 'dashboard', '--db', str(db), '--port', '0', '--experimental-key-vault', str(vault)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            try:
                proc.stdin.write(password + '\n'); proc.stdin.flush()
                url = proc.stdout.readline().strip().split(' ', 1)[1]
                with urllib.request.urlopen(url, timeout=5) as response:
                    self.assertIn('TEST_VAULT_APP', response.read().decode())
            finally:
                proc.terminate(); proc.wait(timeout=5)
                proc.stdin.close(); proc.stdout.close()
