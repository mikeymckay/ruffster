import tempfile
import unittest
from pathlib import Path
from family_activity import store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = store.connect(Path(self.tmp.name) / 'activity.db')

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_clean_stop_has_no_gap(self):
        sid = store.start(self.db, '2026-01-01T00:00:00+00:00')
        store.heartbeat(self.db, sid, '2026-01-01T00:00:10+00:00')
        store.stop(self.db, sid, '2026-01-01T00:00:20+00:00')
        store.start(self.db, '2026-01-01T00:01:00+00:00')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM gaps').fetchone()[0], 0)
        self.assertEqual(self.db.execute('SELECT restarted_after_unclean_exit FROM sessions ORDER BY id DESC LIMIT 1').fetchone()[0], 0)

    def test_unclean_stop_records_last_heartbeat_to_next_start_once(self):
        sid = store.start(self.db, '2026-01-01T00:00:00+00:00')
        store.heartbeat(self.db, sid, '2026-01-01T00:00:10+00:00')
        new = store.start(self.db, '2026-01-01T00:01:00+00:00')
        self.assertEqual(self.db.execute('SELECT restarted_after_unclean_exit FROM sessions WHERE id = ?', (new,)).fetchone()[0], 1)
        self.assertEqual(self.db.execute('SELECT from_at, to_at FROM gaps').fetchall(), [('2026-01-01T00:00:10+00:00', '2026-01-01T00:01:00+00:00')])
        store.stop(self.db, new, '2026-01-01T00:01:10+00:00')
        store.start(self.db, '2026-01-01T00:02:00+00:00')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM gaps').fetchone()[0], 1)
        self.assertEqual(self.db.execute('SELECT restarted_after_unclean_exit FROM sessions ORDER BY id DESC LIMIT 1').fetchone()[0], 0)

    def test_unknown_expired_session_does_not_claim_a_restart(self):
        sid = store.start(self.db, '2026-01-01T00:00:00+00:00')
        self.db.execute("UPDATE sessions SET started_at = 'Start unavailable' WHERE id = ?", (sid,))
        current = store.start(self.db, '2026-01-01T00:01:00+00:00')
        self.assertEqual(self.db.execute('SELECT restarted_after_unclean_exit FROM sessions WHERE id = ?', (current,)).fetchone()[0], 0)

    def test_existing_session_database_adds_restart_marker_without_losing_records(self):
        import sqlite3
        path = Path(self.tmp.name) / 'older.db'
        old = sqlite3.connect(path)
        old.execute('CREATE TABLE sessions (id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, heartbeat_at TEXT NOT NULL, stopped_at TEXT)')
        old.execute('INSERT INTO sessions VALUES (1, ?, ?, NULL)',
                    ('2026-01-01T00:00:00+00:00', '2026-01-01T00:00:10+00:00'))
        old.commit(); old.close()
        migrated = store.connect(path)
        try:
            self.assertEqual(migrated.execute('SELECT started_at, device_id, restarted_after_unclean_exit FROM sessions').fetchall(),
                             [('2026-01-01T00:00:00+00:00', 'legacy', 0)])
            self.assertEqual(store.start(migrated, '2026-01-01T00:01:00+00:00'), 2)
            self.assertEqual(migrated.execute('SELECT restarted_after_unclean_exit FROM sessions WHERE id = 2').fetchone()[0], 1)
        finally:
            migrated.close()

    def test_backwards_clock_does_not_create_negative_gap(self):
        store.start(self.db, '2026-01-02T00:00:00+00:00')
        store.start(self.db, '2026-01-01T00:00:00+00:00')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM gaps').fetchone()[0], 0)

    def test_explicit_observation_gap_requires_active_session_and_ordered_times(self):
        sid = store.start(self.db, '2026-01-01T00:00:00+00:00')
        store.record_gap(self.db, sid, '2026-01-01T00:00:10+00:00', '2026-01-01T00:01:00+00:00')
        self.assertEqual(self.db.execute('SELECT from_at,to_at FROM gaps').fetchall(),
                         [('2026-01-01T00:00:10+00:00','2026-01-01T00:01:00+00:00')])
        with self.assertRaises(ValueError):
            store.record_gap(self.db, sid, '2026-01-01T00:01:00+00:00', '2026-01-01T00:00:10+00:00')
        store.stop(self.db, sid, '2026-01-01T00:01:10+00:00')
        with self.assertRaises(ValueError):
            store.record_gap(self.db, sid, '2026-01-01T00:01:00+00:00', '2026-01-01T00:02:00+00:00')

class ForegroundStorageTests(unittest.TestCase):
    def test_known_and_unknown_samples_are_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = store.connect(Path(tmp) / 'activity.db')
            sid = store.start(db)
            store.record_foreground(db, sid, ('Finder', 'com.apple.finder'))
            store.record_foreground(db, sid, None)
            self.assertEqual(db.execute('SELECT app_name, bundle_id FROM foreground_samples ORDER BY id').fetchall(), [('Finder', 'com.apple.finder'), (None, None)])
            db.close()

class RetentionTests(unittest.TestCase):
    def test_retention_removes_old_samples_and_gaps_preserves_active(self):
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as tmp:
            db = store.connect(Path(tmp)/'db')
            old = store.start(db, '2026-01-01T00:00:00+00:00')
            store.record_foreground(db, old, ('Old', 'old'), '2026-01-01T00:00:01+00:00')
            current = store.start(db, '2026-02-01T00:00:00+00:00')
            store.record_foreground(db, current, ('New', 'new'), '2026-02-01T00:00:01+00:00')
            store.prune(db, 30, datetime(2026, 2, 2, tzinfo=timezone.utc))
            self.assertEqual(db.execute('SELECT app_name FROM foreground_samples').fetchall(), [('New',)])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM gaps').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0], 2)
            store.prune(db, 30, datetime(2026, 3, 5, tzinfo=timezone.utc))
            self.assertEqual(db.execute('SELECT id FROM sessions').fetchall(), [(current,)])
            db.close()

    def test_retention_rejects_invalid_age(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = store.connect(Path(tmp)/'db')
            with self.assertRaises(ValueError):
                store.prune(db, 0)
            db.close()
