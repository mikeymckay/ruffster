from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest

from nacl.public import PrivateKey

from family_activity.encrypted_view import open_projection
from family_activity.plaintext_migration import encrypt_legacy_database
from family_activity import store


def stamp(value):
    return value.astimezone(timezone.utc).isoformat(timespec='microseconds')


class PlaintextMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / 'legacy.sqlite3'
        self.output = self.root / 'encrypted.sqlite3'
        self.parent = PrivateKey.generate()
        self.public = self.root / 'family-public.key'
        self.public.write_bytes(bytes(self.parent.public_key))

    def tearDown(self):
        self.tmp.cleanup()

    def make_legacy_database(self, *, started=None):
        start = started or datetime.now(timezone.utc).replace(microsecond=0)
        db = store.connect(self.source)
        try:
            first = store.start(db, stamp(start))
            first_stop = start + timedelta(seconds=30)
            store.heartbeat(db, first, stamp(first_stop))
            second_start = start + timedelta(seconds=90)
            second = store.start(db, stamp(second_start))
            store.stop(db, second, stamp(second_start + timedelta(seconds=30)))
            with db:
                db.execute('INSERT INTO foreground_samples(session_id,sampled_at,app_name,bundle_id) VALUES (?,?,?,?)',
                           (first, stamp(start + timedelta(seconds=5)), 'LEGACY_PRIVATE_APP', 'example.bundle'))
                db.execute('INSERT INTO foreground_samples(session_id,sampled_at,app_name,bundle_id) VALUES (?,?,?,?)',
                           (first, stamp(start + timedelta(seconds=10)), 'LEGACY_PRIVATE_APP', 'example.bundle'))
                db.execute('INSERT INTO website_samples(session_id,sampled_at,domain) VALUES (?,?,?)',
                           (first, stamp(start + timedelta(seconds=8)), 'example.org'))
                db.execute('INSERT INTO network_intervals(session_id,from_at,to_at,interface,received_bytes,sent_bytes) VALUES (?,?,?,?,?,?)',
                           (first, stamp(start + timedelta(seconds=5)), stamp(start + timedelta(seconds=10)), 'en0', 1234, 567))
                db.execute('INSERT INTO network_settings(session_id,sampled_at,dns_observed,proxy_indicator,vpn_indicator) VALUES (?,?,?,?,?)',
                           (first, stamp(start + timedelta(seconds=10)), 1, 0, None))
                db.execute('INSERT INTO network_changes(session_id,sampled_at,identifier) VALUES (?,?,?)',
                           (first, stamp(start + timedelta(seconds=10)), 'a' * 64))
        finally:
            db.close()
        return start

    def test_migrates_known_schema_to_encrypted_copy_and_preserves_source(self):
        self.make_legacy_database()
        before = self.source.read_bytes()
        result = encrypt_legacy_database(self.source, self.public, self.output, retention_days=30)
        self.assertEqual(result['source_sessions'], 2)
        self.assertGreater(result['inserted_events'], result['retained_events'] - 1)
        self.assertEqual(self.source.read_bytes(), before)
        if os.name != 'nt':  # Windows access is governed by inherited ACLs.
            self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o600)
        self.assertNotIn(b'LEGACY_PRIVATE_APP', self.output.read_bytes())
        db = sqlite3.connect(self.output)
        try:
            self.assertEqual({row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")},
                             {'encrypted_events', 'key_commitment'})
        finally:
            db.close()
        projection, incomplete = open_projection(self.output, self.parent)
        try:
            self.assertFalse(incomplete)
            self.assertEqual(projection.execute('SELECT count(*) FROM sessions').fetchone()[0], 2)
            self.assertEqual(projection.execute('SELECT count(*) FROM gaps').fetchone()[0], 1)
            self.assertEqual(projection.execute('SELECT restarted_after_unclean_exit FROM sessions ORDER BY id').fetchall(),
                             [(0,), (1,)])
            self.assertEqual(projection.execute('SELECT app_name FROM foreground_samples LIMIT 1').fetchone()[0],
                             'LEGACY_PRIVATE_APP')
            self.assertEqual(projection.execute('SELECT domain FROM website_samples').fetchone()[0], 'example.org')
            self.assertEqual(projection.execute('SELECT received_bytes,sent_bytes FROM network_intervals').fetchone(),
                             (1234, 567))
        finally:
            projection.close()
        with self.assertRaises(FileExistsError):
            encrypt_legacy_database(self.source, self.public, self.output)

    def test_uses_original_dates_for_retention(self):
        old = datetime.now(timezone.utc) - timedelta(days=20)
        self.make_legacy_database(started=old)
        result = encrypt_legacy_database(self.source, self.public, self.output, retention_days=7)
        self.assertGreater(result['inserted_events'], 0)
        self.assertEqual(result['retained_events'], 0)
        db = sqlite3.connect(self.output)
        try:
            self.assertEqual(db.execute('SELECT count(*) FROM encrypted_events').fetchone()[0], 0)
        finally:
            db.close()

    def test_cli_reports_conversion_and_preserves_plaintext_source(self):
        self.make_legacy_database()
        result = subprocess.run([sys.executable, '-m', 'family_activity', 'encrypt-legacy',
                                 '--source', str(self.source), '--public-key', str(self.public),
                                 '--output', str(self.output)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('original plaintext file was left untouched', result.stdout)
        self.assertTrue(self.source.is_file())
        self.assertTrue(self.output.is_file())

    def test_rejects_unsupported_or_broken_sources_without_creating_output(self):
        db = sqlite3.connect(self.source)
        db.execute('CREATE TABLE unrelated(secret TEXT)')
        db.commit(); db.close()
        with self.assertRaises(ValueError):
            encrypt_legacy_database(self.source, self.public, self.output)
        self.assertTrue(self.source.exists())
        self.assertFalse(self.output.exists())

    def test_refuses_to_drop_process_network_projection_rows(self):
        db = store.connect(self.source)
        try:
            sid = store.start(db, stamp(datetime.now(timezone.utc).replace(microsecond=0)))
            with db:
                db.execute('INSERT INTO process_network_samples(session_id,sampled_at,process_name,received_bytes,sent_bytes) VALUES (?,?,?,?,?)',
                           (sid, stamp(datetime.now(timezone.utc)), 'Example', 10, 20))
        finally:
            db.close()
        with self.assertRaisesRegex(ValueError, 'cannot preserve'):
            encrypt_legacy_database(self.source, self.public, self.output)
        self.assertFalse(self.output.exists())

    def test_rejects_source_symlink_and_same_path_output(self):
        link = self.root / 'legacy-link.sqlite3'
        link.symlink_to(self.source)
        with self.assertRaises(ValueError):
            encrypt_legacy_database(link, self.public, self.output)
        self.make_legacy_database()
        with self.assertRaises(ValueError):
            encrypt_legacy_database(self.source, self.public, self.source)
        self.assertTrue(self.source.exists())
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
