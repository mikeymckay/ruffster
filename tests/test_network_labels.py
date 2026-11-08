import tempfile
import unittest
from pathlib import Path
from nacl.public import PrivateKey
from family_activity.network_labels import load, set_label

class LabelTests(unittest.TestCase):
    def test_labels_encrypted_and_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'labels'; key = PrivateKey.generate(); token='a'*64
            set_label(path, key, token, 'school')
            self.assertEqual(load(path, key), {token: 'school'})
            self.assertNotIn(b'school', path.read_bytes())
            self.assertNotIn(token.encode(), path.read_bytes())
            set_label(path, key, token, 'home')
            self.assertEqual(load(path, key), {token: 'home'})
            with self.assertRaises(Exception): load(path, PrivateKey.generate())
            with self.assertRaises(ValueError): set_label(path, key, 'invalid', 'home')
            self.assertEqual(load(path, key), {token: 'home'})

    def test_dashboard_displays_family_label(self):
        import subprocess
        import sys
        import urllib.request
        from family_activity.encrypted_agent_store import EncryptedAgentStore
        with tempfile.TemporaryDirectory() as tmp:
            key = PrivateKey.generate(); key_path = Path(tmp)/'key'; key_path.write_bytes(bytes(key))
            labels = Path(tmp)/'labels'; token='b'*64; set_label(labels, key, token, 'school')
            database = Path(tmp)/'db'
            writer = EncryptedAgentStore(database, key.public_key, 30)
            writer.event('start'); writer.event('network_identity', identifier=token); writer.event('stop'); writer.close()
            proc = subprocess.Popen([sys.executable, '-m', 'family_activity', 'dashboard', '--db', str(database), '--port', '0', '--experimental-private-key', str(key_path), '--experimental-network-labels', str(labels)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            try:
                url = proc.stdout.readline().strip().split(' ', 1)[1]
                with urllib.request.urlopen(url, timeout=5) as response:
                    body = response.read().decode()
                self.assertIn('<td>school</td>', body)
                self.assertIn(token, body)
            finally:
                proc.terminate(); proc.wait(timeout=5); proc.stdout.close()
