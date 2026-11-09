import hashlib
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from nacl.public import PrivateKey
from family_activity.encrypted_agent_store import EncryptedAgentStore
from family_activity.encrypted_view import open_projection_bytes
from family_activity.local_share import (PublicKeyShareServer, ShareServer, decode_code,
                                         discover_code, encode_code, fetch, fetch_public_key,
                                         save_encrypted_snapshot)
from family_activity.public_key_file import decode as decode_public_key_file

class LocalShareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = None
        self.thread = None
        self.path = Path(self.tmp.name)/'db'
        self.key = PrivateKey.generate()
        writer = EncryptedAgentStore(self.path,self.key.public_key,30)
        writer.event('start'); writer.event('foreground',application=['TEST_SHARE_PRIVATE_APP','test']); writer.event('stop'); writer.close()
        # Add an old 4 KiB-padded event from the previous on-disk format.
        import json, struct
        from nacl.public import SealedBox
        event = {'version':1,'event':{'type':'website','session':writer.session_id,'at':'2026-11-07T09:00:00+00:00','domain':'example.com'}}
        encoded=json.dumps(event,separators=(',',':')).encode()
        payload=struct.pack('>I',len(encoded))+encoded+bytes(4096-4-len(encoded))
        legacy=SealedBox(self.key.public_key).encrypt(payload)
        old=sqlite3.connect(self.path)
        old.execute('INSERT INTO encrypted_events(expires_on,ciphertext) VALUES (?,?)',('2030-01-01',legacy));old.commit();old.close()
        con = sqlite3.connect(self.path)
        con.execute('CREATE TABLE extra(secret TEXT)'); con.execute('INSERT INTO extra VALUES (?)', ('UNRELATED_SECRET_MARKER',)); con.commit(); con.close()
    def start_report_server(self):
        self.server = ShareServer(self.path, lifetime=30)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        if self.server is not None:
            self.server.shutdown()
            self.thread.join(timeout=5)
            self.server.server_close()
        self.tmp.cleanup()

    def test_pin_token_one_use_and_sanitized_snapshot(self):
        self.start_report_server()
        parts = decode_code(self.server.code)
        bad_pin = encode_code(parts['host'],parts['port'],'0'*64,parts['token'])
        with self.assertRaises(ValueError): fetch(bad_pin)
        self.assertFalse(self.server.used)
        bad_token = encode_code(parts['host'],parts['port'],parts['fingerprint'],'A'*43)
        with self.assertRaises(ValueError): fetch(bad_token)
        self.assertFalse(self.server.used)
        data = fetch(self.server.code)
        self.assertTrue(self.server.used)
        self.assertNotIn(b'TEST_SHARE_PRIVATE_APP',data)
        self.assertNotIn(b'UNRELATED_SECRET_MARKER',data)
        snapshot = sqlite3.connect(':memory:')
        snapshot.deserialize(data)
        self.assertEqual(snapshot.execute('SELECT expiry_version FROM key_commitment').fetchone(), (2,))
        snapshot.close()
        db,_=open_projection_bytes(data,self.key)
        self.assertEqual(db.execute('SELECT app_name FROM foreground_samples').fetchone()[0],'TEST_SHARE_PRIVATE_APP')
        self.assertEqual(db.execute('SELECT domain FROM website_samples').fetchone()[0], 'example.com')
        db.close()
        with self.assertRaises(ValueError): fetch(self.server.code)

    def test_save_encrypted_snapshot_creates_parent_decryptable_ciphertext_only_copy(self):
        from family_activity.encrypted_view import open_projection
        destination = Path(self.tmp.name) / 'report.sqlite3'
        size = save_encrypted_snapshot(self.path, destination)
        self.assertEqual(size, destination.stat().st_size)
        if os.name != 'nt':
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(b'TEST_SHARE_PRIVATE_APP', destination.read_bytes())
        self.assertNotIn(b'UNRELATED_SECRET_MARKER', destination.read_bytes())
        db, _ = open_projection(destination, self.key)
        try:
            self.assertEqual(db.execute('SELECT app_name FROM foreground_samples').fetchone()[0],
                             'TEST_SHARE_PRIVATE_APP')
        finally:
            db.close()
        original = destination.read_bytes()
        with self.assertRaises(FileExistsError):
            save_encrypted_snapshot(self.path, destination)
        self.assertEqual(destination.read_bytes(), original)
        destination.write_bytes(b'old file')
        save_encrypted_snapshot(self.path, destination, overwrite=True)
        self.assertEqual(destination.read_bytes(), original)

    def test_export_report_cli_writes_a_sanitized_file(self):
        import subprocess, sys
        destination = Path(self.tmp.name) / 'cli-report.sqlite3'
        result = subprocess.run([sys.executable, '-m', 'family_activity', 'export-report',
                                 '--db', str(self.path), '--output', str(destination)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Encrypted report copy saved', result.stdout)
        self.assertNotIn('TEST_SHARE_PRIVATE_APP', destination.read_bytes().decode('latin-1'))

    def test_expired_and_invalid_codes_fail(self):
        self.start_report_server()
        self.server.deadline = time.monotonic() - 1
        with self.assertRaises(ValueError): fetch(self.server.code)
        for code in ('', '%%%','a'*2000):
            with self.assertRaises(ValueError): decode_code(code)
        with self.assertRaises(ValueError): encode_code('8.8.8.8',443,'0'*64,'A'*43)

    def test_default_discovery_targets_only_hosts_on_the_route_selected_subnet(self):
        import socket
        from types import SimpleNamespace
        from unittest.mock import patch
        from family_activity import local_share
        adapters = {
            'en0': [SimpleNamespace(family=socket.AF_INET, address='192.168.50.81', netmask='255.255.255.0')],
            'utun0': [SimpleNamespace(family=socket.AF_INET, address='10.8.0.2', netmask='255.255.255.0')],
        }
        fake_psutil = SimpleNamespace(net_if_addrs=lambda: adapters)
        with patch('family_activity.local_share.local_ipv4_address', return_value='192.168.50.81'), \
             patch.dict('sys.modules', {'psutil': fake_psutil}):
            local_address, targets = local_share._local_discovery_targets()
        self.assertEqual(local_address, '192.168.50.81')
        self.assertEqual(len(targets), 254)
        self.assertIn('192.168.50.1', targets)
        self.assertIn('192.168.50.254', targets)
        self.assertNotIn('192.168.50.0', targets)
        self.assertNotIn('192.168.50.255', targets)
        self.assertFalse(any(address.startswith('10.8.0.') for address in targets))

    def test_large_discovery_subnet_falls_back_to_broadcast(self):
        import socket
        from types import SimpleNamespace
        from unittest.mock import patch
        from family_activity import local_share
        adapters = {'en0': [SimpleNamespace(family=socket.AF_INET, address='10.0.0.5', netmask='255.255.0.0')]}
        with patch('family_activity.local_share.local_ipv4_address', return_value='10.0.0.5'), \
             patch.dict('sys.modules', {'psutil': SimpleNamespace(net_if_addrs=lambda: adapters)}):
            local_address, targets = local_share._local_discovery_targets()
        self.assertIsNone(local_address)
        self.assertEqual(targets, (local_share.DISCOVERY_BROADCAST,))

    def test_two_digit_code_resolves_over_local_discovery(self):
        self.start_report_server()
        self.assertEqual(len(self.server.short_code), 2)
        self.assertRegex(self.server.short_code, r'^[0-9]{2}$')
        resolved = discover_code(self.server.short_code, target='127.0.0.1')
        self.assertEqual(decode_code(resolved), decode_code(self.server.code))
        wrong = f'{(int(self.server.short_code) + 1) % 100:02d}'
        with self.assertRaisesRegex(ValueError, 'No nearby computer matched.*System Settings'):
            discover_code(wrong, timeout=0.3, target='127.0.0.1')
        with self.assertRaisesRegex(ValueError, 'two digits'):
            discover_code('8')

    def test_two_digit_discovery_reports_ambiguous_matching_senders(self):
        import json
        from unittest.mock import patch
        from family_activity import local_share

        class FakeSocket:
            def __init__(self):
                self.responses = []

            def __enter__(self): return self
            def __exit__(self, *_): self.close()
            def setsockopt(self, *_): pass
            def bind(self, *_): pass
            def setblocking(self, *_): pass
            def close(self): pass

            def sendto(self, raw, address):
                request = json.loads(raw.decode('ascii'))
                for host, port, fingerprint, token in (
                        ('192.168.1.20', 41001, 'a' * 64, 'A' * 43),
                        ('192.168.1.21', 41002, 'b' * 64, 'B' * 43)):
                    code = encode_code(host, port, fingerprint, token)
                    response = {'v': 1, 'pin': request['pin'], 'nonce': request['nonce'],
                                'connection': code}
                    self.responses.append((json.dumps(response).encode('ascii'), (host, 49372)))

            def recvfrom(self, _):
                if not self.responses:
                    raise BlockingIOError
                return self.responses.pop(0)

        client = FakeSocket()

        def fake_select(readers, writers, errors, timeout):
            if client.responses:
                return [client], [], []
            time.sleep(timeout)
            return [], [], []

        with patch('family_activity.local_share.socket.socket', return_value=client), \
                patch('family_activity.local_share.select.select', side_effect=fake_select):
            with self.assertRaisesRegex(ValueError, 'More than one nearby computer matched'):
                discover_code('42', timeout=0.2, target='192.168.1.5')

    def test_public_key_share_is_pinned_one_use_and_contains_no_private_key(self):
        server = PublicKeyShareServer(self.key.public_key, '127.0.0.1', lifetime=30)
        thread = threading.Thread(target=server.serve_once, daemon=True); thread.start()
        try:
            code = server.code
            parts = decode_code(code)
            wrong_pin = encode_code(parts['host'], parts['port'], '0'*64, parts['token'])
            with self.assertRaises(ValueError): fetch_public_key(wrong_pin)
            self.assertFalse(server.used)
            data = fetch_public_key(code)
            self.assertTrue(server.used)
            self.assertEqual(bytes(decode_public_key_file(data)), bytes(self.key.public_key))
            self.assertNotIn(bytes(self.key), data)
            with self.assertRaises(ValueError): fetch_public_key(code)
        finally:
            server.cancel(); thread.join(timeout=3); server.server_close()

    def test_fetch_public_key_cli_writes_only_typed_public_key_to_stdout(self):
        import subprocess, sys
        server = PublicKeyShareServer(self.key.public_key, '127.0.0.1', lifetime=30)
        thread = threading.Thread(target=server.serve_once, daemon=True); thread.start()
        try:
            result = subprocess.run([sys.executable, '-m', 'family_activity', 'fetch-public-key'],
                                    input=(server.code+'\n').encode(), capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(bytes(decode_public_key_file(result.stdout)), bytes(self.key.public_key))
        finally:
            server.cancel(); thread.join(timeout=3); server.server_close()

    def test_fetch_public_key_cli_can_write_to_a_path_for_windowed_setup(self):
        import subprocess, sys
        server = PublicKeyShareServer(self.key.public_key, '127.0.0.1', lifetime=30)
        thread = threading.Thread(target=server.serve_once, daemon=True); thread.start()
        destination = Path(self.tmp.name) / 'family-public.key'
        try:
            result = subprocess.run([sys.executable, '-m', 'family_activity', 'fetch-public-key',
                                     '--code', server.code, '--output', str(destination)],
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, b'')
            self.assertEqual(bytes(decode_public_key_file(destination.read_bytes())), bytes(self.key.public_key))
            self.assertTrue(server.used)
        finally:
            server.cancel(); thread.join(timeout=3); server.server_close()

    def test_share_cli_termination_cleans_up_temporary_tls_material(self):
        import os
        import subprocess
        import sys
        environment = os.environ.copy(); environment['TMPDIR'] = self.tmp.name
        cancel_file = Path(self.tmp.name) / 'cancel-share'
        proc = subprocess.Popen([sys.executable, '-m', 'family_activity', 'share', '--db', str(self.path),
                                 '--lifetime', '30', '--cancel-file', str(cancel_file)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment, text=True)
        try:
            self.assertIn('Temporary encrypted report transfer', proc.stdout.readline())
            code = proc.stdout.readline().strip()
            self.assertTrue(code)
            self.assertTrue(list(Path(self.tmp.name).glob('family-share-*')))
            cancel_file.touch()
            proc.wait(timeout=5)
            self.assertEqual(proc.returncode, 0)
            self.assertFalse(list(Path(self.tmp.name).glob('family-share-*')))
        finally:
            if proc.poll() is None: proc.kill(); proc.wait()
            proc.stdout.close(); proc.stderr.close()

    def test_share_cli_can_publish_code_to_file_for_windowed_tray(self):
        import os, subprocess, sys, time
        code_path = Path(self.tmp.name) / 'share-code.txt'
        cancel_path = Path(self.tmp.name) / 'share-cancel'
        environment = os.environ.copy(); environment['TMPDIR'] = self.tmp.name
        proc = subprocess.Popen([sys.executable, '-m', 'family_activity', 'share', '--db', str(self.path),
                                 '--host', '127.0.0.1', '--lifetime', '20', '--code-file', str(code_path),
                                 '--cancel-file', str(cancel_path)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment)
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not code_path.exists() and proc.poll() is None:
                time.sleep(.02)
            self.assertTrue(code_path.is_file(), proc.stderr.read() if proc.poll() is not None else 'code not written')
            code = code_path.read_text('ascii')
            self.assertRegex(code, r'^[0-9]{2}$')
            snapshot = fetch(discover_code(code, target='127.0.0.1'))
            self.assertGreater(len(snapshot), 100)
            self.assertEqual(proc.wait(timeout=5), 0, proc.stderr.read())
        finally:
            if proc.poll() is None: proc.terminate(); proc.wait(timeout=5)
            proc.stdout.close(); proc.stderr.close()

    def test_share_cli_cancellation_file_closes_tls_material_cleanly(self):
        import os, subprocess, sys, time
        code_path = Path(self.tmp.name) / 'share-cancel-code.txt'
        cancel_path = Path(self.tmp.name) / 'share-cancel-token'
        environment = os.environ.copy(); environment['TMPDIR'] = self.tmp.name
        proc = subprocess.Popen([sys.executable, '-m', 'family_activity', 'share', '--db', str(self.path),
                                 '--host', '127.0.0.1', '--lifetime', '20', '--code-file', str(code_path),
                                 '--cancel-file', str(cancel_path)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment)
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not code_path.exists() and proc.poll() is None: time.sleep(.02)
            self.assertTrue(code_path.exists())
            self.assertTrue(list(Path(self.tmp.name).glob('family-share-*')))
            cancel_path.touch()
            self.assertEqual(proc.wait(timeout=5), 0, proc.stderr.read())
            self.assertFalse(list(Path(self.tmp.name).glob('family-share-*')))
        finally:
            if proc.poll() is None: proc.terminate(); proc.wait(timeout=5)
            proc.stdout.close(); proc.stderr.close()
