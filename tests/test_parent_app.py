import http.client
import html
import json
from contextlib import closing
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
from nacl.public import PublicKey
from family_activity.encrypted_agent_store import EncryptedAgentStore
from family_activity.parent_app import ParentServer
from family_activity.public_key_file import decode

class ParentAppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)/'parent'
        self.server = ParentServer(self.folder)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f'http://127.0.0.1:{self.server.server_port}'
        self.cookie = ''

    def tearDown(self):
        self.server.shutdown(); self.thread.join(timeout=5); self.server.server_close(); self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        h = {'Origin': self.origin}
        if self.cookie: h['Cookie'] = self.cookie
        h.update(headers or {})
        if isinstance(body, dict):
            body = json.dumps(body).encode(); h['Content-Type']='application/json'
        conn.request(method, path, body=body, headers=h)
        response = conn.getresponse(); content = response.read(); result = response.status, dict(response.getheaders()), content
        conn.close()
        return result

    def login(self):
        status, headers, _ = self.request('POST', '/api/login', {'token':self.server.token})
        self.assertEqual(status, 200)
        self.cookie = headers['Set-Cookie'].split(';', 1)[0]
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', headers['Set-Cookie'])

    def create_parent_key(self, password):
        self.assertEqual(self.request('POST', '/api/create',
                                      {'passphrase':password, 'confirm':password})[0], 200)
        code, _, backup = self.request('GET', '/api/backup')
        self.assertEqual(code, 200)
        self.assertEqual(self.request('POST', '/api/confirm-key-backup', {'confirmed':True})[0], 200)
        return backup

    def test_conversation_prompts_are_cautious_and_tied_to_observations(self):
        from family_activity.parent_app import _conversation_prompts
        report = {'sessions':[('start','heartbeat','stop')], 'incomplete':False, 'gaps':[],
                  'networks':[], 'network_settings':{'dns_observed':True,'proxy_indicator':False,'vpn_indicator':False}}
        prompts = _conversation_prompts(report)
        self.assertTrue(any('cannot confirm' in prompt for prompt in prompts))
        self.assertFalse(any(term in ' '.join(prompts).lower() for term in ('suspicious','misconduct','tampering')))
        report.update({'sessions':[], 'incomplete':True, 'gaps':[('from','to')],
                       'networks':[{'label':None}],
                       'network_settings':{'dns_observed':None,'proxy_indicator':True,'vpn_indicator':None}})
        prompts = _conversation_prompts(report)
        self.assertTrue(any('no recent agent sessions' in prompt for prompt in prompts))
        self.assertTrue(any('coverage is incomplete' in prompt for prompt in prompts))
        self.assertTrue(any('unobserved intervals' in prompt for prompt in prompts))
        self.assertTrue(any('unlabeled' in prompt for prompt in prompts))
        self.assertTrue(any('school-managed' in prompt for prompt in prompts))

    def test_parent_dashboard_has_a_live_four_step_setup_guide(self):
        status, _, page = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.assertIn(b'id="setup-progress"', page)
        self.assertEqual(page.count(b'class="step-number"'), 4)
        self.assertIn(b'id="next-step"', page)
        self.assertIn(b'id="key-state"', page)
        self.assertIn(b'id="child-setup" hidden', page)
        self.assertIn(b'id="backup-required"', page)
        self.assertIn(b'id="download-backup-required"', page)
        self.assertIn(b'id="backup-confirm-check"', page)
        self.assertIn(b'id="confirm-backup"', page)
        self.assertIn(b'id="report-transfer" hidden', page)
        self.assertIn(b'add more computers later and review each one separately', page)
        self.assertIn(b'id="report-device"', page)
        self.assertIn(b'id="device-label-form"', page)
        self.assertIn(b'New observations are added to the report already saved here.', page)
        self.assertIn(b'exact copies of the same records are ignored', page)
        self.assertIn(b'I already set up parent access', page)
        self.assertIn(b'Estimated time', page)
        self.assertIn(b'Measured interface bytes', page)
        self.assertIn(b'Observed settings', page)
        self.assertIn(b'Past seven days', page)
        self.assertIn(b'During school hours', page)
        self.assertIn(b'Network protection and computer settings', page)
        self.assertIn(b'Monitoring coverage details', page)
        self.assertIn(b'id="snapshot-note"', page)
        self.assertIn(b'id="report-timezone-note"', page)
        self.assertIn(b'home router', page)
        self.assertIn(b'mobile hotspot', page)
        self.assertIn(b'Ask the school before changing settings', page)
        status, _, script = self.request('GET', '/app.js')
        self.assertEqual(status, 200)
        self.assertIn(b'function updateSetupProgress()', script)
        self.assertIn(b"$('key-form').hidden = status.unlocked", script)
        self.assertIn(b"$('key-state').hidden = !status.unlocked", script)
        self.assertIn(b"$('child-setup').hidden = !(status.unlocked && status.backup_confirmed)", script)
        self.assertIn(b"$('backup-required').hidden = !(status.unlocked && !status.backup_confirmed)", script)
        self.assertIn(b"post('/api/public-key-share', {})", script)
        self.assertIn(b"/api/confirm-key-backup", script)
        self.assertIn(b"$('report-transfer').hidden = !status.unlocked", script)
        self.assertIn(b"status.has_report", script)
        self.assertIn(b'Recorded agent runtime', script)
        self.assertIn(b'cannot confirm every sample succeeded', script)
        self.assertIn(b'This does not show whether websites were used.', script)
        self.assertIn(b'This does not prove monitoring was continuous.', script)
        status, _, styles = self.request('GET', '/app.css')
        self.assertEqual(status, 200)
        self.assertIn(b'.steps li.current', styles)
        self.assertIn(b'select:focus-visible', styles)
        self.assertIn(b'button:disabled', styles)
        status, _, mascot = self.request('GET', '/ruffster-mascot.webp')
        self.assertEqual(status, 200)
        self.assertTrue(mascot.startswith(b'RIFF'))
        self.assertIn(b'RUFFSTER', page)

    def test_parent_cli_closes_loopback_server_on_termination(self):
        import socket
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as folder:
            process=subprocess.Popen([sys.executable,'-m','family_activity','parent','--no-browser',
                                      '--data-dir',str(Path(folder)/'parent')],
                                     stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                process.stdout.readline()
                url=process.stdout.readline().strip()
                self.assertTrue(url.startswith('http://127.0.0.1:'))
                from urllib.parse import urlsplit
                parsed=urlsplit(url)
                with socket.create_connection(('127.0.0.1',parsed.port),timeout=2):
                    pass
                process.terminate()
                self.assertEqual(process.wait(timeout=5),0)
                with self.assertRaises(OSError):
                    socket.create_connection(('127.0.0.1',parsed.port),timeout=1)
            finally:
                if process.poll() is None: process.kill(); process.wait()
                process.stdout.close(); process.stderr.close()

    def test_access_controls_and_one_use_login(self):
        self.assertEqual(self.request('GET', '/api/status')[0], 403)
        self.assertEqual(self.request('POST', '/api/login', {'token':self.server.token}, {'Origin':'https://evil.example'})[0], 403)
        self.assertEqual(self.request('POST', '/api/login', {'token':'wrong'})[0], 403)
        self.login()
        self.assertEqual(self.request('GET', '/api/status')[0], 200)
        self.assertEqual(self.request('GET', '/api/settings')[0], 403)
        self.assertEqual(self.request('GET', '/api/status', headers={'Host':'evil.example'})[0], 403)
        self.assertEqual(self.request('POST', '/api/login', {'token':self.server.token})[0], 403)
        self.assertEqual(self.request('POST', '/api/lock', {}, {'Origin':'https://evil.example'})[0], 403)

    def test_authenticated_api_reads_reject_other_loopback_origins(self):
        self.login()
        self.assertEqual(self.request('GET', '/api/status', headers={
            'Origin': f'http://127.0.0.1:{self.server.server_port + 1}'})[0], 403)
        self.assertEqual(self.request('GET', '/api/status', headers={
            'Sec-Fetch-Site': 'same-site'})[0], 403)
        self.assertEqual(self.request('GET', '/api/status', headers={
            'Sec-Fetch-Site': 'cross-site'})[0], 403)
        self.assertEqual(self.request('GET', '/api/status', headers={
            'Sec-Fetch-Site': 'same-origin'})[0], 200)

    @unittest.skipUnless(shutil.which('google-chrome'), 'requires Google Chrome')
    def test_chrome_launcher_session_can_read_same_origin_parent_api(self):
        with tempfile.TemporaryDirectory() as profile:
            result = subprocess.run([
                shutil.which('google-chrome'), '--headless=new', '--no-sandbox',
                '--disable-gpu', '--disable-dev-shm-usage', '--no-first-run',
                '--disable-background-networking', '--virtual-time-budget=3000',
                f'--user-data-dir={profile}', '--dump-dom', self.server.url,
            ], capture_output=True, text=True, timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        message = re.search(r'<p id="message"[^>]*>(.*?)</p>', result.stdout, re.S)
        self.assertIsNotNone(message, 'dashboard status message was not rendered')
        self.assertEqual(html.unescape(message.group(1)).strip(), '')

    def test_parent_key_auto_locks_after_inactivity(self):
        import time
        from family_activity.parent_app import KEY_IDLE_TIMEOUT_SECONDS
        self.login(); password='638204'
        self.assertEqual(self.request('POST','/api/create',{'passphrase':password,'confirm':password})[0],200)
        self.assertTrue(json.loads(self.request('GET','/api/status')[2])['unlocked'])
        self.server._private_key_last_used = time.monotonic() - KEY_IDLE_TIMEOUT_SECONDS - 1
        self.assertFalse(json.loads(self.request('GET','/api/status')[2])['unlocked'])
        self.assertEqual(self.request('GET','/api/settings')[0],403)
        self.assertEqual(self.request('POST','/api/unlock',{'passphrase':password})[0],200)
        self.assertTrue(json.loads(self.request('GET','/api/status')[2])['unlocked'])

    def test_parent_access_creation_rejects_non_six_digit_pin(self):
        self.login()
        for pin in ('12345', '1234567', '12ab56'):
            with self.subTest(pin=pin):
                self.assertEqual(self.request('POST', '/api/create',
                                              {'passphrase':pin, 'confirm':pin})[0], 400)
        self.assertFalse(self.server.vault.exists())

    def test_parent_key_backup_restores_on_empty_parent_install_without_overwrite(self):
        import base64
        self.login(); password='638204'
        self.assertEqual(self.request('POST','/api/create',{'passphrase':password,'confirm':password})[0],200)
        backup=self.request('GET','/api/backup')[2]
        expected_public=bytes(self.server.private_key.public_key)
        self.server.private_key=None
        self.server.vault.unlink()
        body={'backup':base64.b64encode(backup).decode('ascii'),'passphrase':'incorrect backup phrase'}
        self.assertEqual(self.request('POST','/api/restore-key',body)[0],400)
        self.assertFalse(self.server.vault.exists())
        body['passphrase']=password
        self.assertEqual(self.request('POST','/api/restore-key',body)[0],200)
        self.assertEqual(bytes(self.server.private_key.public_key),expected_public)
        self.assertEqual(self.server.vault.read_bytes(),backup)
        self.assertEqual(self.request('POST','/api/restore-key',body)[0],409)
        self.assertEqual(self.server.vault.read_bytes(),backup)

    def test_parent_dashboard_exposes_key_restore_only_for_empty_vault(self):
        status, _, page=self.request('GET','/')
        self.assertEqual(status,200)
        self.assertIn(b'id="restore-wrap"',page)
        self.assertIn(b'id="restore-file"',page)
        status, _, script=self.request('GET','/app.js')
        self.assertEqual(status,200)
        self.assertIn(b"$('restore-wrap').hidden = status.has_key",script)
        self.assertIn(b"/api/restore-key",script)

    def test_child_pairing_waits_for_parent_backup_download_and_confirmation(self):
        self.login()
        password = '638204'
        self.assertEqual(self.request('POST', '/api/create',
                                      {'passphrase':password, 'confirm':password})[0], 200)
        status = json.loads(self.request('GET', '/api/status')[2])
        self.assertFalse(status['backup_confirmed'])
        self.assertEqual(self.request('GET', '/api/public-key-share')[0], 404)
        self.assertEqual(self.request('GET', '/api/public')[0], 403)
        self.assertEqual(self.request('POST', '/api/confirm-key-backup', {'confirmed':True})[0], 400)

        code, headers, backup = self.request('GET', '/api/backup')
        self.assertEqual(code, 200)
        self.assertIn('ruffster-parent-backup.vault', headers['Content-Disposition'])
        self.assertEqual(self.request('POST', '/api/confirm-key-backup', {'confirmed':True})[0], 200)
        status = json.loads(self.request('GET', '/api/status')[2])
        self.assertTrue(status['backup_confirmed'])
        self.assertEqual(self.request('GET', '/api/public')[0], 200)
        self.assertEqual(self.request('GET', '/api/public-key-share')[0], 404)
        self.assertIsNone(self.server._key_share_server)

        reopened = ParentServer(self.folder)
        try:
            self.assertTrue(reopened.backup_confirmed)
            self.assertEqual(reopened.retention_days, 30)
        finally:
            reopened.server_close()

    def test_parent_setup_import_report_lock_and_preserve_existing(self):
        self.login()
        password='638204'
        self.create_parent_key(password)
        self.assertEqual(json.loads(self.request('GET', '/api/settings')[2])['retention_days'], 30)
        self.assertEqual(self.request('POST', '/api/retention', {'retention_days':8})[0], 400)
        self.assertEqual(self.request('POST', '/api/retention', {'retention_days':90})[0], 200)
        self.assertEqual(self.server.retention_days, 90)
        self.assertEqual(self.request('POST', '/api/create', {'passphrase':password,'confirm':password})[0], 409)
        schedule = {'timezone':'Europe/Vienna', 'days':[0,1,2,3,4], 'start':'08:30', 'end':'15:00'}
        self.assertEqual(self.request('POST', '/api/schedule', schedule)[0], 200)
        self.assertEqual(json.loads(self.request('GET', '/api/schedule')[2])['schedule'], schedule)
        self.assertNotIn(b'Europe/Vienna', self.server.schedule.read_bytes())
        self.assertEqual(self.request('POST', '/api/schedule', {**schedule, 'end':'07:00'})[0], 400)
        self.assertEqual(json.loads(self.request('GET', '/api/schedule')[2])['schedule'], schedule)
        status, _, public = self.request('GET', '/api/public')
        self.assertEqual(status, 200)
        backup = self.request('GET', '/api/backup')[2]
        self.assertNotIn(bytes(self.server.private_key), backup)
        path = Path(self.tmp.name)/'source.db'
        writer = EncryptedAgentStore(path, decode(public), 30)
        from datetime import datetime, timedelta, timezone
        sample = datetime.now(timezone.utc)
        writer.event('start')
        writer.event('foreground', application=['SYNTHETIC_PARENT_APP','test'])
        writer.event('network_identity', identifier='c'*64)
        writer.event('network_settings', dns_observed=True, proxy_indicator=False, vpn_indicator=None)
        writer.event('network', at=sample.isoformat(), intervals=[[
            (sample-timedelta(seconds=15)).isoformat(), sample.isoformat(), 'en0', 1024, 256]])
        writer.event('website', domain='youtube.com', at=(sample-timedelta(seconds=15)).isoformat())
        writer.event('website', domain='youtube.com', at=sample.isoformat())
        writer.event('process_network_status', state='enabled', at=sample.isoformat())
        writer.event('process_network', process='SyntheticBrowser', received_bytes=2400000000,
                     sent_bytes=123456, at=sample.isoformat())
        writer.event('stop'); writer.close()
        import sqlite3
        extra = sqlite3.connect(path)
        extra.execute('CREATE TABLE unrelated(secret TEXT)')
        extra.execute('INSERT INTO unrelated VALUES (?)', ('UNRELATED_PLAINTEXT_MARKER',))
        extra.commit(); extra.close()
        self.assertEqual(self.request('POST', '/api/import', path.read_bytes())[0], 200)
        status, _, report = self.request('GET', '/api/report')
        self.assertEqual(status, 200)
        report_data=json.loads(report)
        self.assertTrue(any('cannot confirm' in prompt for prompt in report_data['conversation_prompts']))
        self.assertEqual(len(report_data['sessions']), 1)
        self.assertIn('agent_runtime', report_data)
        self.assertGreaterEqual(report_data['agent_runtime']['seconds'], 0)
        self.assertEqual(report_data['agent_runtime']['sessions'], 1)
        self.assertEqual(report_data['website_observations']['count'], 2)
        self.assertEqual(report_data['website_observations']['latest_at'], sample.isoformat())
        self.assertTrue(report_data['contexts']['schedule_configured'])
        self.assertEqual(report_data['report_timezone'], 'Europe/Vienna')
        self.assertIsNotNone(report_data['recorded_through'])
        self.assertIsNotNone(report_data['generated_at'])
        self.assertEqual(report_data['traffic_usage']['today'], [['en0', 1024, 256]])
        self.assertEqual(report_data['traffic_usage']['week'], [['en0', 1024, 256]])
        self.assertEqual(report_data['process_traffic']['status'], 'enabled')
        self.assertEqual(report_data['process_traffic']['today'], [['SyntheticBrowser', 2400000000, 123456]])
        self.assertTrue(report_data['traffic_contexts']['schedule_configured'])
        self.assertIn('school', report_data['traffic_contexts'])
        self.assertIn('home', report_data['traffic_contexts'])
        self.assertIn('school_network', report_data['traffic_contexts'])
        self.assertIn('other_network', report_data['traffic_contexts'])
        for context in ('home', 'school_network', 'other_network'):
            self.assertIn(context, report_data['contexts']['apps'])
            self.assertIn(context, report_data['contexts']['sites'])
        settings = report_data['network_settings']
        self.assertTrue(settings['dns_observed'])
        self.assertFalse(settings['proxy_indicator'])
        self.assertIsNone(settings['vpn_indicator'])
        self.assertNotIn('nameserver', report.decode().lower())
        self.assertEqual(json.loads(report)['site_categories']['today'], [['Video', 15.0]])
        self.assertEqual(self.request('POST', '/api/network-label', {'identifier':'c'*64, 'label':'school'})[0], 200)
        self.assertNotIn(b'school', self.server.labels.read_bytes())
        self.assertEqual(json.loads(self.request('GET', '/api/report')[2])['networks'][0]['label'], 'school')
        self.assertEqual(self.request('POST', '/api/network-label', {'identifier':'c'*64, 'label':None})[0], 200)
        self.assertIsNone(json.loads(self.request('GET', '/api/report')[2])['networks'][0]['label'])
        self.assertEqual(self.request('POST', '/api/import', b'invalid bytes and not a database')[0], 400)
        self.assertEqual(self.request('GET', '/api/report')[0], 200)
        self.assertNotIn(b'SYNTHETIC_PARENT_APP', self.server.data.read_bytes())
        self.assertNotIn(b'SyntheticBrowser', self.server.data.read_bytes())
        self.assertNotIn(b'UNRELATED_PLAINTEXT_MARKER', self.server.data.read_bytes())
        self.assertEqual(self.request('POST', '/api/lock', {})[0], 200)
        self.assertEqual(self.request('GET', '/api/report')[0], 403)
        self.assertEqual(self.request('POST', '/api/unlock', {'passphrase':'wrong password long enough'})[0], 400)
        self.assertEqual(self.request('POST', '/api/unlock', {'passphrase':password})[0], 200)

    def test_parent_retention_prunes_old_encrypted_events_and_keeps_key(self):
        from datetime import datetime, timedelta, timezone
        import sqlite3
        self.login(); password='638204'
        self.create_parent_key(password)
        public=self.request('GET','/api/public')[2]
        path=Path(self.tmp.name)/'old-source.db'; writer=EncryptedAgentStore(path,decode(public),30)
        old=datetime.now(timezone.utc)-timedelta(days=10)
        writer.event('start',at=(old-timedelta(seconds=15)).isoformat())
        writer.event('foreground',application=['OLD_RETENTION_TEST_APP','test'],at=(old-timedelta(seconds=15)).isoformat())
        writer.event('foreground',application=['OLD_RETENTION_TEST_APP','test'],at=old.isoformat())
        writer.event('stop',at=(old+timedelta(seconds=15)).isoformat()); writer.close()
        self.assertEqual(self.request('POST','/api/import',path.read_bytes())[0],200)
        self.assertEqual(len(json.loads(self.request('GET','/api/report')[2])['sessions']),1)
        self.assertEqual(self.request('POST','/api/retention',{'retention_days':7})[0],200)
        pruned_report=json.loads(self.request('GET','/api/report')[2])
        self.assertEqual(len(pruned_report['sessions']),0)
        self.assertIsNone(pruned_report['recorded_through'])
        self.assertEqual(json.loads(self.request('GET','/api/settings')[2])['retention_days'],7)
        db=sqlite3.connect(self.server.data)
        try: self.assertEqual(db.execute('SELECT count(*) FROM encrypted_events').fetchone()[0],0)
        finally: db.close()
        self.assertNotIn(b'OLD_RETENTION_TEST_APP',self.server.data.read_bytes())
        self.assertEqual(self.request('POST','/api/unlock',{'passphrase':password})[0],200)

    def test_parent_can_delete_local_report_and_sidecars_without_deleting_key(self):
        self.login(); password='638204'
        self.create_parent_key(password)
        self.assertEqual(self.request('GET','/api/report-backup')[0],403)
        public=self.request('GET','/api/public')[2]
        source=Path(self.tmp.name)/'source.db'; writer=EncryptedAgentStore(source,decode(public),30)
        writer.event('start'); writer.event('foreground',application=['DELETE_ME_TEST_APP','test']); writer.event('stop'); writer.close()
        self.assertEqual(self.request('POST','/api/import',source.read_bytes())[0],200)
        import sqlite3
        connection=sqlite3.connect(self.server.data)
        connection.execute('CREATE TABLE unrelated(secret TEXT)')
        connection.execute('INSERT INTO unrelated VALUES (?)',('UNRELATED_REPORT_MARKER',))
        connection.commit(); connection.close()
        status, headers, backup=self.request('GET','/api/report-backup')
        self.assertEqual(status,200)
        self.assertIn('ruffster-report.sqlite3',headers['Content-Disposition'])
        self.assertNotIn(b'DELETE_ME_TEST_APP',backup)
        self.assertNotIn(b'UNRELATED_REPORT_MARKER',backup)
        from family_activity.encrypted_view import open_projection_bytes
        projected, _ = open_projection_bytes(backup,self.server.private_key)
        try:
            self.assertEqual(projected.execute('SELECT app_name FROM foreground_samples').fetchone()[0], 'DELETE_ME_TEST_APP')
        finally:
            projected.close()
        sidecars=[Path(str(self.server.data)+suffix) for suffix in ('-wal','-shm','-journal')]
        for item in sidecars: item.write_bytes(b'encrypted sqlite sidecar')
        self.assertEqual(self.request('POST','/api/lock',{})[0],200)
        self.assertEqual(self.request('POST','/api/delete-report',{})[0],403)
        self.assertEqual(self.request('POST','/api/unlock',{'passphrase':password})[0],200)
        self.assertEqual(self.request('POST','/api/delete-report',{})[0],200)
        self.assertFalse(self.server.data.exists())
        self.assertTrue(all(not item.exists() for item in sidecars))
        self.assertTrue(self.server.vault.exists())
        self.assertEqual(self.request('GET','/api/settings')[0],200)
        self.assertEqual(self.request('POST','/api/unlock',{'passphrase':password})[0],200)

    def test_local_share_imports_after_parent_unlock(self):
        from family_activity.local_share import ShareServer
        self.login(); password='638204'
        self.create_parent_key(password)
        public = self.request('GET','/api/public')[2]
        source = Path(self.tmp.name)/'source.db'
        writer = EncryptedAgentStore(source, decode(public), 30)
        writer.event('start'); writer.event('foreground', application=['TRANSFER_TEST_APP','test']); writer.event('stop'); writer.close()
        share = ShareServer(source, lifetime=30)
        thread = threading.Thread(target=share.serve_forever, daemon=True); thread.start()
        try:
            self.assertEqual(self.request('POST','/api/sync',{'code':share.code})[0],200)
            status, _, content = self.request('GET','/api/report')
            self.assertEqual(status,200)
            self.assertEqual(len(json.loads(content)['sessions']),1)
            self.assertNotIn(b'TRANSFER_TEST_APP',self.server.data.read_bytes())
            self.assertTrue(share.used)
        finally:
            share.shutdown(); thread.join(timeout=5); share.server_close()

    def test_encrypted_file_export_opens_in_parent_dashboard(self):
        from family_activity.local_share import save_encrypted_snapshot
        self.login(); self.create_parent_key('638204')
        public = self.request('GET', '/api/public')[2]
        source = Path(self.tmp.name)/'child.db'
        writer = EncryptedAgentStore(source, decode(public), 30)
        writer.event('start')
        writer.event('foreground', application=['FILE_RETURN_TEST_APP', 'test'])
        writer.event('stop'); writer.close()
        report_file = Path(self.tmp.name)/'ruffster-report.sqlite3'
        self.assertGreater(save_encrypted_snapshot(source, report_file), 0)
        self.assertEqual(self.request('POST', '/api/import', report_file.read_bytes())[0], 200)
        report = json.loads(self.request('GET', '/api/report')[2])
        self.assertEqual(len(report['sessions']), 1)
        self.assertNotIn(b'FILE_RETURN_TEST_APP', self.server.data.read_bytes())

    def test_imported_reports_merge_without_losing_newer_data_or_duplicating_events(self):
        import sqlite3
        from datetime import datetime, timedelta, timezone
        self.login(); self.create_parent_key('638204')
        public = decode(self.request('GET', '/api/public')[2])
        now = datetime.now(timezone.utc) - timedelta(seconds=10)

        def snapshot(filename, timestamp, app):
            path = Path(self.tmp.name) / filename
            writer = EncryptedAgentStore(path, public, 30)
            writer.event('start', at=timestamp.isoformat())
            writer.event('foreground', at=timestamp.isoformat(), application=[app, 'synthetic'])
            writer.event('foreground', at=(timestamp + timedelta(seconds=1)).isoformat(),
                         application=[app, 'synthetic'])
            writer.event('stop', at=(timestamp + timedelta(seconds=2)).isoformat())
            writer.close()
            return path.read_bytes()

        earlier = snapshot('earlier-report.db', now - timedelta(minutes=2), 'EarlierSyntheticApp')
        newer = snapshot('newer-report.db', now, 'NewerSyntheticApp')
        self.assertEqual(self.request('POST', '/api/import', earlier)[0], 200)
        self.assertEqual(self.request('POST', '/api/import', newer)[0], 200)
        with closing(sqlite3.connect(self.server.data)) as database, database:
            merged_count = database.execute('SELECT count(*) FROM encrypted_events').fetchone()[0]
        # Re-importing an older copy must not remove newer observations. Re-importing
        # the same snapshot must not make durations or event counts grow twice.
        self.assertEqual(self.request('POST', '/api/import', earlier)[0], 200)
        with closing(sqlite3.connect(self.server.data)) as database, database:
            self.assertEqual(database.execute('SELECT count(*) FROM encrypted_events').fetchone()[0], merged_count)
        report = json.loads(self.request('GET', '/api/report')[2])
        self.assertEqual(len(report['sessions']), 2)
        self.assertEqual({entry[0] for entry in report['apps']['today']},
                         {'EarlierSyntheticApp', 'NewerSyntheticApp'})
        stored = self.server.data.read_bytes()
        self.assertNotIn(b'EarlierSyntheticApp', stored)
        self.assertNotIn(b'NewerSyntheticApp', stored)
        with closing(sqlite3.connect(self.server.data)) as database:
            self.assertEqual({row[0] for row in database.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}, {'key_commitment', 'encrypted_events'})

    def test_parent_report_separates_computers_and_saves_encrypted_names(self):
        from datetime import datetime, timedelta, timezone
        from family_activity import encrypted_view
        self.login(); self.create_parent_key('638204')
        public = decode(self.request('GET', '/api/public')[2])
        snapshots = []
        for filename, app in (('child-one.db', 'SyntheticAnnikaApp'),
                              ('child-two.db', 'SyntheticSiblingApp')):
            path = Path(self.tmp.name) / filename
            writer = EncryptedAgentStore(path, public, 30)
            start = datetime.now(timezone.utc) - timedelta(minutes=2)
            writer.event('start', at=start.isoformat())
            writer.event('foreground', at=start.isoformat(), application=[app, 'synthetic'])
            writer.event('foreground', at=(start + timedelta(seconds=30)).isoformat(),
                         application=[app, 'synthetic'])
            writer.event('stop', at=(start + timedelta(seconds=31)).isoformat())
            device_id = writer.device_id
            writer.close()
            snapshots.append((device_id, app, path.read_bytes()))
        for _, _, snapshot in snapshots:
            self.assertEqual(self.request('POST', '/api/import', snapshot)[0], 200)

        combined = json.loads(self.request('GET', '/api/report')[2])
        self.assertEqual(len(combined['devices']), 2)
        self.assertEqual({device['device_id'] for device in combined['devices']},
                         {device_id for device_id, _, _ in snapshots})
        for device_id, own_app, other_snapshot in (
                (snapshots[0][0], snapshots[0][1], snapshots[1]),
                (snapshots[1][0], snapshots[1][1], snapshots[0])):
            status, _, content = self.request('GET', f'/api/report?device={device_id}')
            self.assertEqual(status, 200)
            report = json.loads(content)
            self.assertEqual(report['selected_device'], device_id)
            self.assertEqual(len(report['sessions']), 1)
            app_names = {entry[0] for entry in report['apps']['today']}
            self.assertIn(own_app, app_names)
            self.assertNotIn(other_snapshot[1], app_names)
        self.assertEqual(self.request('GET', '/api/report?device=not-a-device')[0], 400)

        device_id = snapshots[0][0]
        self.assertEqual(self.request('POST', '/api/device-label',
                                      {'device_id': device_id, 'label': "Annika's MacBook"})[0], 200)
        named = json.loads(self.request('GET', f'/api/report?device={device_id}')[2])
        self.assertEqual(next(device['label'] for device in named['devices']
                              if device['device_id'] == device_id), "Annika's MacBook")
        self.assertNotIn(b"Annika's MacBook", self.server.data.read_bytes())

    def test_import_normalizes_legacy_expiry_before_marking_records_current(self):
        import sqlite3
        from datetime import date, timedelta
        self.login(); self.create_parent_key('638204')
        public = decode(self.request('GET', '/api/public')[2])
        source = Path(self.tmp.name) / 'legacy-expiry-report.db'
        writer = EncryptedAgentStore(source, public, 30)
        writer.event('start'); writer.close()
        with closing(sqlite3.connect(source)) as database, database:
            current_expiry = database.execute('SELECT expires_on FROM encrypted_events').fetchone()[0]
            legacy_expiry = (date.fromisoformat(current_expiry) + timedelta(days=1)).isoformat()
            database.execute('UPDATE key_commitment SET expiry_version=1')
            database.execute('UPDATE encrypted_events SET expires_on=?', (legacy_expiry,))
        self.assertEqual(self.request('POST', '/api/import', source.read_bytes())[0], 200)
        with closing(sqlite3.connect(self.server.data)) as database, database:
            self.assertEqual(database.execute('SELECT expiry_version FROM key_commitment').fetchone()[0], 2)
            self.assertEqual(database.execute('SELECT expires_on FROM encrypted_events').fetchone()[0], current_expiry)

    def test_report_pairing_error_points_mac_users_to_local_network_access(self):
        from unittest.mock import patch
        self.login(); self.create_parent_key('638204')
        with patch('family_activity.local_share.discover_code', side_effect=ValueError('not found')):
            status, _, content = self.request('POST', '/api/sync', {'code': '00'})
        self.assertEqual(status, 400)
        self.assertIn('System Settings > Privacy & Security > Local Network', json.loads(content)['error'])

    def test_parent_can_start_and_stop_one_time_public_key_pairing(self):
        from unittest.mock import patch
        from family_activity.local_share import decode_code, fetch_public_key
        self.login(); password='638204'
        self.assertEqual(self.request('GET','/api/public-key-share')[0],404)
        self.create_parent_key(password)
        self.assertEqual(self.request('GET','/api/public-key-share')[0],404)
        self.assertIsNone(self.server._key_share_server)
        self.assertEqual(self.request('POST','/api/public-key-share',{},
                                      {'Origin':'https://evil.example'})[0],403)
        self.assertIsNone(self.server._key_share_server)
        with patch('family_activity.local_share.local_ipv4_address', return_value='127.0.0.1'):
            status, _, first = self.request('POST','/api/public-key-share',{})
            self.assertEqual(status,200)
            code = json.loads(first)['code']
            self.assertRegex(code, r'^[0-9]{2}$')
            first_token = decode_code(self.server._key_share_server.code)['token']
            second = json.loads(self.request('POST','/api/public-key-share',{})[2])['code']
            self.assertEqual(code,second)
            with patch('family_activity.local_share.DISCOVERY_BROADCAST', '127.0.0.1'):
                data = fetch_public_key(code)
            self.assertEqual(decode(data), decode(self.request('GET','/api/public')[2]))
            self.assertEqual(self.request('GET','/api/public-key-share')[0],404)
            self.assertEqual(self.request('POST','/api/public-key-share',{})[0],200)
            restarted = json.loads(self.request('POST','/api/public-key-share',{})[2])['code']
            self.assertNotEqual(decode_code(self.server._key_share_server.code)['token'],first_token)
            active = self.server._key_share_server
            self.assertEqual(self.request('POST','/api/public-key-share/stop',{})[0],200)
            self.assertEqual(self.request('GET','/api/public-key-share')[0],404)
            self.assertEqual(self.request('POST','/api/lock',{})[0],200)
            if self.server._key_share_thread:
                self.server._key_share_thread.join(timeout=3)
            self.assertIsNone(self.server._key_share_server)
            self.assertIsNone(self.server._key_share_thread)
            self.assertFalse(active.used)
