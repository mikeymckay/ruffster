import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone
from family_activity import network, store
from family_activity.network import NetworkSampler, coverage_gap, sampling_gap_limit

class NetworkTests(unittest.TestCase):
    def test_sampling_interval_must_be_finite_and_positive(self):
        for value in (0, -1, float('nan'), float('inf'), float('-inf'), 'not-a-number'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'finite positive'):
                network.validate_sampling_interval(value)
        self.assertEqual(network.validate_sampling_interval('0.5'), 0.5)

    def test_coverage_gap_detects_suspend_and_ignores_short_or_backwards_intervals(self):
        start = '2026-11-07T10:00:00+00:00'
        short = '2026-11-07T10:00:20+00:00'
        long = '2026-11-07T10:00:45+00:00'
        self.assertEqual(sampling_gap_limit(10), 20)
        self.assertIsNone(coverage_gap(start, 0, short, 15, 10))
        # Some system monotonic clocks pause during sleep, while UTC wall time advances.
        self.assertEqual(coverage_gap(start, 0, long, 15, 10), (start, long))
        self.assertEqual(coverage_gap(start, 0, long, 45, 10), (start, long))
        self.assertIsNone(coverage_gap(long, 45, start, 50, 10))

    def test_sample_missing_reset_and_long_gap_break_attribution(self):
        sampler = NetworkSampler(10)
        t0 = '2026-11-07T10:00:00+00:00'
        t1 = '2026-11-07T10:00:10+00:00'
        self.assertEqual(sampler.observe({'en0': (100, 200)}, t0, 0), [])
        self.assertEqual(sampler.observe({'en0': (120, 230)}, t1, 10), [(t0,t1,'en0',20,30)])
        self.assertEqual(sampler.observe(None, '2026-11-07T10:00:20+00:00', 20), [])
        self.assertEqual(sampler.observe({'en0': (300, 400)}, '2026-11-07T10:00:30+00:00', 30), [])
        self.assertEqual(sampler.observe({'en0': (1, 2)}, '2026-11-07T10:00:40+00:00', 40), [])
        self.assertEqual(sampler.observe({'en0': (4, 5)}, '2026-11-07T10:05:00+00:00', 300), [])

    def test_retention_removes_intervals(self):
        with tempfile.TemporaryDirectory() as directory:
            db = store.connect(Path(directory)/'db')
            session = store.start(db, '2026-01-01T00:00:00+00:00')
            store.record_network(db, session, [('2026-01-01T00:00:00+00:00','2026-01-01T00:00:10+00:00','en0',5,9)])
            store.prune(db, 30, datetime(2026, 3, 1, tzinfo=timezone.utc))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM network_intervals').fetchone()[0], 0)
            db.close()

    def test_zero_traffic_interfaces_are_not_stored(self):
        sampler = NetworkSampler(10)
        sampler.observe({'en0': (1, 2), 'utun0': (3, 4)}, '2026-11-07T10:00:00+00:00', 0)
        rows = sampler.observe({'en0': (3, 2), 'utun0': (3, 4)}, '2026-11-07T10:00:10+00:00', 10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2:], ('en0',2,0))
