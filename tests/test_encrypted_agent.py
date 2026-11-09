import os
from contextlib import redirect_stdout
import hashlib
import sqlite3
import subprocess
import sys
import tempfile
import time
import signal
import io
import threading
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from nacl.public import PrivateKey
from family_activity import encrypted_store, store
from family_activity.encrypted_agent_store import EncryptedAgentStore


def agent_bootstrap_that_stops_after(delay):
    """Stop through the agent's shutdown handler on hosts without POSIX SIGTERM."""
    return (
        'import signal, threading\n'
        'from family_activity.__main__ import main\n'
        'register = signal.signal\n'
        'def register_and_stop(signum, handler):\n'
        '    previous = register(signum, handler)\n'
        '    if signum == signal.SIGTERM:\n'
        f'        threading.Timer({delay!r}, lambda: handler(signum, None)).start()\n'
        '    return previous\n'
        'signal.signal = register_and_stop\n'
        'main()\n'
    )

class EncryptedAgentTests(unittest.TestCase):
    def test_device_identity_is_stable_across_agent_restarts_and_encrypted(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = PrivateKey.generate()
            path = Path(tmp) / 'activity.sqlite3'
            first = EncryptedAgentStore(path, parent.public_key, 30)
            device_id = first.device_id
            first.event('start')
            first.close()
            second = EncryptedAgentStore(path, parent.public_key, 30)
            self.assertEqual(second.device_id, device_id)
            second.event('stop')
            second.close()
            with closing(sqlite3.connect(path)) as database:
                events = database.execute('SELECT ciphertext FROM encrypted_events ORDER BY id').fetchall()
            decrypted = [encrypted_store.open_event(parent, row[0]) for row in events]
            self.assertEqual({event['device_id'] for event in decrypted}, {device_id})
            self.assertNotIn(device_id.encode(), path.read_bytes())

    def test_opted_in_process_network_samples_are_encrypted_and_labeled(self):
        from unittest.mock import patch
        from family_activity.__main__ import agent
        from family_activity.process_network import ProcessBytes

        class SyntheticSampler:
            def __init__(self): self.pending = True; self.failure = None; self.closed = False
            def drain(self):
                if self.pending:
                    self.pending = False
                    return (ProcessBytes('SyntheticBrowser', 4096, 512),)
                return ()
            def close(self): self.closed = True

        with tempfile.TemporaryDirectory() as tmp:
            parent = PrivateKey.generate()
            public = Path(tmp) / 'parent.pub'; public.write_bytes(bytes(parent.public_key))
            database = Path(tmp) / 'activity.sqlite3'
            sampler = SyntheticSampler()
            previous = signal.getsignal(signal.SIGTERM)
            # Invoke the agent's graceful handler directly: os.kill(SIGTERM)
            # terminates the entire test process on Windows.
            real_signal = signal.signal
            def register_and_stop(signum, handler):
                previous_handler = real_signal(signum, handler)
                if signum == signal.SIGTERM:
                    threading.Timer(1.0, lambda: handler(signum, None)).start()
                return previous_handler
            try:
                with patch('family_activity.__main__.start_status', return_value=None), \
                     patch('family_activity.__main__.signal.signal', side_effect=register_and_stop), \
                     patch('family_activity.process_network.MacProcessNetworkSampler', return_value=sampler), \
                     redirect_stdout(io.StringIO()):
                    agent(database, .1, public_key_path=public, experimental_process_network=True)
            finally:
                real_signal(signal.SIGTERM, previous)
            connection = sqlite3.connect(database)
            events = [encrypted_store.open_event(parent, row[0])
                      for row in connection.execute('SELECT ciphertext FROM encrypted_events ORDER BY id')]
            connection.close()
            self.assertEqual([event['state'] for event in events if event['type'] == 'process_network_status'], ['enabled'])
            sample = next(event for event in events if event['type'] == 'process_network')
            self.assertEqual((sample['process'], sample['received_bytes'], sample['sent_bytes']),
                             ('SyntheticBrowser', 4096, 512))
            self.assertNotIn(b'SyntheticBrowser', database.read_bytes())
            self.assertTrue(sampler.closed)

    def test_key_commitment_and_plaintext_database_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'db'
            parent, other = PrivateKey.generate(), PrivateKey.generate()
            secured = EncryptedAgentStore(path, parent.public_key, 30)
            secured.event('foreground', application=['PRIVATE_APP_VALUE_98435', 'bundle.example'])
            secured.close()
            with self.assertRaises(ValueError): EncryptedAgentStore(path, other.public_key, 30)
            with self.assertRaises(ValueError): store.connect(path)
            self.assertNotIn(b'PRIVATE_APP_VALUE_98435', path.read_bytes())
            plain = Path(tmp)/'plain'
            db = store.connect(plain); db.close()
            with self.assertRaises(ValueError): EncryptedAgentStore(plain, parent.public_key, 30)

    def test_retention_by_expiry_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = PrivateKey.generate()
            secured = EncryptedAgentStore(Path(tmp)/'db', parent.public_key, 30)
            before = datetime.now(timezone.utc)
            secured.event('start')
            after = datetime.now(timezone.utc)
            self.assertEqual(secured.db.execute('SELECT count(*) FROM encrypted_events').fetchone()[0], 1)
            expires_on = secured.db.execute('SELECT expires_on FROM encrypted_events').fetchone()[0]
            self.assertIn(expires_on, {
                (before.date() + timedelta(days=30)).isoformat(),
                (after.date() + timedelta(days=30)).isoformat(),
            })
            expiry = datetime.fromisoformat(expires_on).replace(tzinfo=timezone.utc)
            secured.prune(expiry - timedelta(days=1))
            self.assertEqual(secured.db.execute('SELECT count(*) FROM encrypted_events').fetchone()[0], 1)
            secured.prune(expiry)
            self.assertEqual(secured.db.execute('SELECT count(*) FROM encrypted_events').fetchone()[0], 0)
            secured.close()

    def test_legacy_expiry_metadata_is_adjusted_once_without_rewriting_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = PrivateKey.generate()
            path = Path(tmp) / 'legacy-agent.db'
            now = datetime.now(timezone.utc)
            event = {'type': 'start', 'session': 'legacy-session', 'at': now.isoformat()}
            ciphertext = encrypted_store.seal_event(parent.public_key, event)
            legacy_expiry = (now.date() + timedelta(days=31)).isoformat()
            db = sqlite3.connect(path)
            db.execute('CREATE TABLE encrypted_events (id INTEGER PRIMARY KEY, expires_on TEXT NOT NULL, ciphertext BLOB NOT NULL)')
            db.execute('CREATE TABLE key_commitment (fingerprint TEXT NOT NULL)')
            fingerprint = hashlib.sha256(bytes(parent.public_key)).hexdigest()
            db.execute('INSERT INTO key_commitment VALUES (?)', (fingerprint,))
            db.execute('INSERT INTO encrypted_events(expires_on, ciphertext) VALUES (?, ?)', (legacy_expiry, ciphertext))
            db.commit()
            db.close()

            secured = EncryptedAgentStore(path, parent.public_key, 30)
            corrected_expiry, preserved_ciphertext = secured.db.execute(
                'SELECT expires_on, ciphertext FROM encrypted_events').fetchone()
            self.assertEqual(corrected_expiry, (now.date() + timedelta(days=30)).isoformat())
            self.assertEqual(preserved_ciphertext, ciphertext)
            self.assertEqual(encrypted_store.open_event(parent, preserved_ciphertext), event)
            self.assertEqual(secured.db.execute('SELECT expiry_version FROM key_commitment').fetchone(), (2,))
            secured.close()

            reopened = EncryptedAgentStore(path, parent.public_key, 30)
            self.assertEqual(reopened.db.execute('SELECT expires_on FROM encrypted_events').fetchone()[0], corrected_expiry)
            reopened.close()

    def test_agent_writes_only_encrypted_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = PrivateKey.generate()
            public = Path(tmp)/'parent.pub'; public.write_bytes(bytes(parent.public_key))
            path = Path(tmp)/'db'
            proc = subprocess.Popen([sys.executable, '-c', agent_bootstrap_that_stops_after(.8),
                                     'agent', '--db', str(path), '--interval', '.1',
                                     '--experimental-public-key', str(public)],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                line = proc.stdout.readline()
                self.assertIn('Monitoring heartbeat active', line)
                proc.wait(timeout=5)
                self.assertEqual(proc.returncode, 0)
                con = sqlite3.connect(path)
                events = [encrypted_store.open_event(parent, row[0]) for row in con.execute('SELECT ciphertext FROM encrypted_events ORDER BY id')]
                self.assertEqual(events[0]['type'], 'start')
                self.assertEqual(events[-1]['type'], 'stop')
                self.assertIn('tick', [event['type'] for event in events])
                self.assertEqual({row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}, {'encrypted_events', 'key_commitment'})
                con.close()
            finally:
                if proc.poll() is None: proc.kill(); proc.wait()
                proc.stdout.close(); proc.stderr.close()

    def test_agent_refuses_to_collect_without_parent_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'activity.sqlite3'
            result=subprocess.run([sys.executable,'-m','family_activity','agent','--db',str(path)],
                                  capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,2)
            self.assertIn('parent public key is required',result.stderr)
            self.assertIn('plaintext activity collection is disabled',result.stderr)
            self.assertFalse(path.exists())

    def test_agent_rejects_invalid_intervals_before_creating_activity_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            parent = PrivateKey.generate()
            public = folder / 'parent.pub'
            public.write_bytes(bytes(parent.public_key))
            for value in ('0', '-0.1', 'nan', 'inf', '-inf', '3600.01', '1e308'):
                with self.subTest(interval=value):
                    database = folder / f'{value.replace("-", "negative-")}.sqlite3'
                    result = subprocess.run(
                        [sys.executable, '-m', 'family_activity', 'agent', '--db', str(database),
                         f'--interval={value}', '--experimental-public-key', str(public)],
                        capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn('finite positive number', result.stderr)
                    self.assertFalse(database.exists())

    def test_process_network_mode_requires_visible_status_helper_before_database_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            parent = PrivateKey.generate()
            public = folder / 'parent.pub'
            public.write_bytes(bytes(parent.public_key))
            database = folder / 'activity.sqlite3'
            bootstrap = ("import sys; from family_activity.__main__ import main; "
                         "sys.platform='darwin'; main()")
            result = subprocess.run(
                [sys.executable, '-c', bootstrap, 'agent', '--db', str(database),
                 '--experimental-public-key', str(public), '--experimental-process-network'],
                capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 2)
            self.assertIn('process traffic', result.stderr)
            self.assertIn('--experimental-status-helper', result.stderr)
            self.assertFalse(database.exists())

    def test_agent_help_states_parent_key_encryption_requirement(self):
        result=subprocess.run([sys.executable,'-m','family_activity','--help'],
                              capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0)
        self.assertIn('Run disclosed monitoring with mandatory parent-key encryption',
                      ' '.join(result.stdout.split()))

    def test_agent_records_detected_runtime_sampling_gaps_in_encrypted_store(self):
        from family_activity.encrypted_view import open_projection
        bootstrap = ("import sys; from family_activity import network; calls=0; "
                    "def_gap=None; exec('def gap(a,b,c,d,e):\\n global calls\\n calls += 1\\n return (a,c) if calls == 2 else None'); "
                    "network.coverage_gap=gap; from family_activity.__main__ import main; ")
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp); db_path=folder/'activity.sqlite3'
            parent=PrivateKey.generate(); public=folder/'parent.pub'; public.write_bytes(bytes(parent.public_key))
            bootstrap += 'import signal,threading; _register=signal.signal; '
            bootstrap += 'signal.signal=lambda sig,handler: (_register(sig,handler), '
            bootstrap += 'threading.Timer(.8,lambda: handler(sig,None)).start() '
            bootstrap += 'if sig==signal.SIGTERM else None)[0]; main()'
            argv=[sys.executable,'-c',bootstrap,'agent','--db',str(db_path),'--interval','.1',
                  '--experimental-public-key',str(public)]
            proc=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                startup = proc.stdout.readline()
                self.assertIn('Monitoring heartbeat active', startup, proc.stderr.read())
                proc.wait(timeout=5)
                self.assertEqual(proc.returncode,0,proc.stderr.read())
                event_db=sqlite3.connect(db_path)
                events=[encrypted_store.open_event(parent,row[0]) for row in event_db.execute('SELECT ciphertext FROM encrypted_events ORDER BY id')]
                event_db.close()
                gap_events=[event for event in events if event['type']=='gap']
                self.assertEqual(len(gap_events),1)
                projection,_=open_projection(db_path,parent)
                self.assertEqual(projection.execute('SELECT count(*) FROM gaps').fetchone()[0],1)
                projection.close()
            finally:
                if proc.poll() is None: proc.kill(); proc.wait()
                proc.stdout.close(); proc.stderr.close()

    @unittest.skipIf(os.name == 'nt', 'Mac helper executable cannot run on a Windows host')
    def test_network_settings_only_mode_starts_required_visible_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent=PrivateKey.generate(); public=Path(tmp)/'parent.pub'; public.write_bytes(bytes(parent.public_key))
            marker=Path(tmp)/'status-started'; helper=Path(tmp)/'status-helper'
            helper.write_text('#!/usr/bin/env python3\nfrom pathlib import Path\nimport time\nPath(' + repr(str(marker)) + ').touch()\nprint("READY", flush=True)\ntime.sleep(60)\n')
            helper.chmod(0o700)
            database=Path(tmp)/'activity.sqlite3'
            bootstrap=("import sys; from family_activity.__main__ import main; "
                       "from family_activity import network_settings; sys.platform='darwin'; "
                       "network_settings.observe_macos=lambda: "
                       "{'dns_observed': None, 'proxy_indicator': None, 'vpn_indicator': None}; "
                       "main()")
            proc=subprocess.Popen([sys.executable,'-c',bootstrap,'agent','--db',str(database),
                                   '--interval','.1','--experimental-public-key',str(public),
                                   '--experimental-network','--experimental-network-settings',
                                   '--experimental-status-helper',str(helper)],
                                  stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                first=proc.stdout.readline()
                line=first if 'Monitoring heartbeat active' in first else proc.stdout.readline()
                self.assertIn('Monitoring heartbeat active',line)
                self.assertTrue(marker.exists())
                # SIGTERM can arrive during a bounded network-system call;
                # allow time for that call and status-helper cleanup to finish.
                proc.terminate(); proc.wait(timeout=15)
                self.assertEqual(proc.returncode,0)
            finally:
                if proc.poll() is None: proc.kill(); proc.wait()
                proc.stdout.close(); proc.stderr.close()

    @unittest.skipIf(os.name == 'nt', 'Mac helper executable cannot run on a Windows host')
    def test_agent_records_pseudonymous_network_identity_with_device_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            parent = PrivateKey.generate()
            public = folder / 'parent.pub'; public.write_bytes(bytes(parent.public_key))
            network_key = folder / 'network.key'; network_key.write_bytes(os.urandom(32))
            helper = folder / 'status-helper'
            helper.write_text('#!/usr/bin/env python3\nimport time\nprint("READY", flush=True)\ntime.sleep(60)\n')
            helper.chmod(0o700)
            database = folder / 'activity.sqlite3'
            bootstrap = ("import sys; from family_activity.__main__ import main; "
                         "from family_activity import network_identity; "
                         "network_identity.macos_identifier=lambda key: 'a'*64; "
                         "sys.platform='darwin'; main()")
            process = subprocess.Popen([sys.executable, '-c', bootstrap, 'agent', '--db', str(database),
                                        '--interval', '.1', '--experimental-public-key', str(public),
                                        '--experimental-network', '--experimental-network-key', str(network_key),
                                        '--experimental-status-helper', str(helper)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                first = process.stdout.readline()
                line = first if 'Monitoring heartbeat active' in first else process.stdout.readline()
                self.assertIn('Monitoring heartbeat active', line)
                time.sleep(.25)
                # Network sampling can be in a bounded OS subprocess when SIGTERM
                # arrives. Give that operation and the visible helper shutdown
                # time to finish on a busy hosted macOS runner.
                process.terminate(); process.wait(timeout=15)
                self.assertEqual(process.returncode, 0, process.stderr.read())
                connection = sqlite3.connect(database)
                events = [encrypted_store.open_event(parent, row[0]) for row in
                          connection.execute('SELECT ciphertext FROM encrypted_events ORDER BY id')]
                connection.close()
                identity = [event for event in events if event['type'] == 'network_identity']
                self.assertEqual(len(identity), 1)
                self.assertEqual(identity[0]['type'], 'network_identity')
                self.assertEqual(identity[0]['identifier'], 'a' * 64)
            finally:
                if process.poll() is None: process.kill(); process.wait()
                process.stdout.close(); process.stderr.close()
