import sqlite3
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from nacl.public import PrivateKey
from family_activity.encrypted_agent_store import EncryptedAgentStore
from family_activity.encrypted_view import open_projection

class EncryptedViewTests(unittest.TestCase):
    def test_process_network_event_reconstruction_requires_opt_in_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = PrivateKey.generate(); path = Path(tmp) / 'process-traffic.sqlite3'
            writer = EncryptedAgentStore(path, parent.public_key, 30)
            writer.event('start')
            writer.event('process_network_status', state='enabled')
            writer.event('process_network', process='Safari', received_bytes=5000, sent_bytes=700)
            writer.event('process_network_status', state='unavailable')
            writer.event('stop'); writer.close()
            db, incomplete = open_projection(path, parent)
            self.assertFalse(incomplete)
            self.assertEqual(db.execute('SELECT process_name,received_bytes,sent_bytes FROM process_network_samples').fetchall(),
                             [('Safari', 5000, 700)])
            self.assertEqual(db.execute('SELECT state FROM process_network_status ORDER BY id').fetchall(),
                             [('enabled',), ('unavailable',)])
            db.close()

            invalid = Path(tmp) / 'unannounced-process-traffic.sqlite3'
            writer = EncryptedAgentStore(invalid, parent.public_key, 30)
            writer.event('start')
            writer.event('process_network', process='Safari', received_bytes=1, sent_bytes=0)
            writer.close()
            with self.assertRaises(ValueError):
                open_projection(invalid, parent)

    def test_encrypted_gap_event_reconstructs_unobserved_interval(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent=PrivateKey.generate(); path=Path(tmp)/'encrypted.db'
            writer=EncryptedAgentStore(path,parent.public_key,30)
            writer.event('start',at='2026-11-07T10:00:00+00:00')
            writer.event('gap',from_at='2026-11-07T10:00:15+00:00',
                         to_at='2026-11-07T10:01:00+00:00',at='2026-11-07T10:01:00+00:00')
            writer.event('tick',at='2026-11-07T10:01:00+00:00')
            writer.event('stop',at='2026-11-07T10:01:15+00:00'); writer.close()
            db,incomplete=open_projection(path,parent)
            self.assertFalse(incomplete)
            self.assertEqual(db.execute('SELECT from_at,to_at FROM gaps').fetchall(),
                             [('2026-11-07T10:00:15+00:00','2026-11-07T10:01:00+00:00')])
            db.close()

    def test_rebuild_observations_and_gap_without_plaintext_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = PrivateKey.generate(); path = Path(tmp)/'encrypted.db'
            writer = EncryptedAgentStore(path, parent.public_key, 30)
            writer.event('start')
            writer.event('foreground', application=['PRIVATE_VIEW_APP_741', 'com.example'])
            writer.event('network', intervals=[['2026-11-07T09:00:00+00:00', '2026-11-07T09:00:15+00:00', 'en0', 42, 8]])
            writer.event('heartbeat')
            writer.close()
            writer = EncryptedAgentStore(path, parent.public_key, 30)
            writer.event('start'); writer.event('stop'); writer.close()
            db, incomplete = open_projection(path, parent)
            self.assertFalse(incomplete)
            self.assertEqual(db.execute('SELECT app_name FROM foreground_samples').fetchall(), [('PRIVATE_VIEW_APP_741',)])
            self.assertEqual(db.execute('SELECT received_bytes, sent_bytes FROM network_intervals').fetchall(), [(42, 8)])
            self.assertEqual(db.execute('SELECT count(*) FROM gaps').fetchone()[0], 1)
            self.assertEqual(db.execute('PRAGMA database_list').fetchone()[2], '')
            db.close()
            self.assertNotIn(b'PRIVATE_VIEW_APP_741', path.read_bytes())
            with self.assertRaises(ValueError): open_projection(path, PrivateKey.generate())

    def test_missing_start_shows_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = PrivateKey.generate(); path = Path(tmp)/'encrypted.db'
            writer = EncryptedAgentStore(path, parent.public_key, 30)
            writer.event('heartbeat'); writer.close()
            db, incomplete = open_projection(path, parent)
            self.assertTrue(incomplete)
            self.assertEqual(db.execute('SELECT started_at FROM sessions').fetchone()[0], 'Start unavailable')
            db.close()

    def test_parent_dashboard_and_wrong_key_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = PrivateKey.generate(); path = Path(tmp)/'db'; key = Path(tmp)/'key'
            key.write_bytes(bytes(parent))
            writer = EncryptedAgentStore(path, parent.public_key, 30)
            writer.event('start'); writer.event('foreground', application=['PRIVATE_TEST_APP', 'app']); writer.event('stop'); writer.close()
            def run_dashboard():
                process = subprocess.Popen([sys.executable, '-m', 'family_activity', 'dashboard', '--db', str(path), '--port', '0', '--experimental-private-key', str(key)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
                return process, process.stdout.readline().strip().split(' ', 1)[1]
            proc, url = run_dashboard()
            try:
                with urllib.request.urlopen(url, timeout=5) as response:
                    self.assertIn('PRIVATE_TEST_APP', response.read().decode())
            finally:
                proc.terminate(); proc.wait(timeout=5); proc.stdout.close()
            key.write_bytes(bytes(PrivateKey.generate()))
            proc, url = run_dashboard()
            try:
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(url, timeout=5)
                self.assertEqual(error.exception.code, 503)
                error.exception.close()
            finally:
                proc.terminate(); proc.wait(timeout=5); proc.stdout.close()

    def test_corrupt_record_fails_closed(self):
        from nacl.exceptions import CryptoError
        with tempfile.TemporaryDirectory() as tmp:
            parent = PrivateKey.generate(); path = Path(tmp)/'encrypted.db'
            writer = EncryptedAgentStore(path, parent.public_key, 30)
            writer.event('start'); writer.close()
            db = sqlite3.connect(path)
            data = bytearray(db.execute('SELECT ciphertext FROM encrypted_events').fetchone()[0])
            data[-1] ^= 1
            db.execute('UPDATE encrypted_events SET ciphertext = ?', (bytes(data),))
            db.commit(); db.close()
            with self.assertRaises(CryptoError): open_projection(path, parent)

    def test_network_identifier_reconstructed_and_invalid_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = PrivateKey.generate(); path = Path(tmp)/'db'
            writer = EncryptedAgentStore(path, parent.public_key, 30)
            writer.event('start'); writer.event('network_identity', identifier='a'*64)
            writer.event('network_identity', identifier=None); writer.event('stop'); writer.close()
            db, _ = open_projection(path, parent)
            self.assertEqual(db.execute('SELECT identifier FROM network_changes ORDER BY id').fetchall(), [('a'*64,), (None,)])
            db.close()
            writer = EncryptedAgentStore(path, parent.public_key, 30)
            writer.event('start'); writer.event('network_identity', identifier='not-a-token'); writer.close()
            with self.assertRaises(ValueError): open_projection(path, parent)

    def test_tick_reconstructs_heartbeat_application_and_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = PrivateKey.generate(); path = Path(tmp)/'encrypted.db'
            writer = EncryptedAgentStore(path, parent.public_key, 30)
            writer.event('start')
            writer.event('tick', application=['App', 'app'], intervals=[['2026-11-07T09:00:00+00:00','2026-11-07T09:00:15+00:00','en0',100,25]])
            writer.event('stop'); writer.close()
            db, incomplete = open_projection(path, parent)
            self.assertFalse(incomplete)
            self.assertEqual(db.execute('SELECT app_name FROM foreground_samples').fetchone()[0], 'App')
            self.assertEqual(db.execute('SELECT received_bytes, sent_bytes FROM network_intervals').fetchone(), (100,25))
            db.close()

    def test_network_settings_reconstruction_and_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = PrivateKey.generate(); path = Path(tmp)/'db'
            writer = EncryptedAgentStore(path, parent.public_key, 30)
            writer.event('start'); writer.event('network_settings', dns_observed=True, proxy_indicator=False, vpn_indicator=None); writer.event('stop'); writer.close()
            db, _ = open_projection(path, parent)
            self.assertEqual(db.execute('SELECT dns_observed, proxy_indicator, vpn_indicator FROM network_settings').fetchone(), (1,0,None))
            db.close()
            writer = EncryptedAgentStore(path, parent.public_key, 30)
            writer.event('start'); writer.event('network_settings', dns_observed='invalid', proxy_indicator=None, vpn_indicator=None); writer.close()
            with self.assertRaises(ValueError): open_projection(path, parent)
