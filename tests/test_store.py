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

    def test_unclean_stop_records_last_heartbeat_to_next_start_once(self):
        sid = store.start(self.db, '2026-01-01T00:00:00+00:00')
        store.heartbeat(self.db, sid, '2026-01-01T00:00:10+00:00')
        new = store.start(self.db, '2026-01-01T00:01:00+00:00')
        self.assertEqual(self.db.execute('SELECT from_at, to_at FROM gaps').fetchall(), [('2026-01-01T00:00:10+00:00', '2026-01-01T00:01:00+00:00')])
        store.stop(self.db, new, '2026-01-01T00:01:10+00:00')
        store.start(self.db, '2026-01-01T00:02:00+00:00')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM gaps').fetchone()[0], 1)

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
