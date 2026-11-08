import unittest
import os
import time
from datetime import datetime, timedelta, timezone
from family_activity.reports import (_system_local_midnight_utc, agent_runtime,
                                     contextual_traffic_usage, estimates, traffic_usage)
from zoneinfo import ZoneInfo

class ReportsTests(unittest.TestCase):
    def test_traffic_usage_sums_each_interface_for_local_day_and_seven_days(self):
        zone = ZoneInfo('Europe/Vienna')
        as_of = datetime(2026, 11, 8, 12, tzinfo=zone)
        intervals = [
            ('2026-11-08T08:00:00+01:00', '2026-11-08T08:00:10+01:00', 'en0', 1000, 200),
            ('2026-11-03T08:00:00+01:00', '2026-11-03T08:00:10+01:00', 'en0', 300, 50),
            ('2026-11-08T08:00:00+01:00', '2026-11-08T08:00:10+01:00', 'utun3', 70, 30),
            ('2026-11-01T08:00:00+01:00', '2026-11-01T08:00:10+01:00', 'en0', 900, 900),
            ('2026-11-08T13:00:00+01:00', '2026-11-08T13:00:10+01:00', 'en0', 500, 500),
        ]
        result = traffic_usage(intervals, as_of, zone)
        self.assertEqual(result['today'], [('en0', 1000, 200), ('utun3', 70, 30)])
        self.assertEqual(result['week'], [('en0', 1300, 250), ('utun3', 70, 30)])

    def test_traffic_usage_groups_intervals_by_end_date_and_ignores_invalid_values(self):
        zone = ZoneInfo('Europe/Vienna')
        as_of = datetime(2026, 1, 2, 0, 30, tzinfo=zone)
        intervals = [
            ('2026-01-01T22:59:50+00:00', '2026-01-01T23:00:10+00:00', 'en0', 12, 5),
            ('2026-01-01T22:00:00+00:00', '2026-01-01T22:00:10+00:00', 'en0', -1, 2),
            ('2026-01-02T00:00:00+01:00', '2026-01-02T00:00:00+01:00', 'en0', 1, 1),
        ]
        result = traffic_usage(intervals, as_of, zone)
        self.assertEqual(result['today'], [('en0', 12, 5)])
        self.assertEqual(result['week'], [('en0', 12, 5)])

    def test_traffic_usage_requires_aware_report_time(self):
        with self.assertRaises(ValueError):
            traffic_usage([], datetime(2026, 11, 8))

    def test_contextual_traffic_apportions_school_time_and_keeps_home_labelled_bytes_separate(self):
        as_of = datetime(2026, 11, 6, 10, tzinfo=timezone.utc)
        schedule = {'timezone': 'Europe/Vienna', 'days': [4], 'start': '08:30', 'end': '15:00'}
        intervals = [
            (1, '2026-11-06T06:40:00+00:00', '2026-11-06T06:40:10+00:00', 'en0', 1000, 100),
            (1, '2026-11-06T07:20:00+00:00', '2026-11-06T07:20:10+00:00', 'en0', 100, 10),
            (1, '2026-11-06T07:29:50+00:00', '2026-11-06T07:30:00+00:00', 'en0', 50, 5),
            (1, '2026-11-06T07:29:55+00:00', '2026-11-06T07:30:05+00:00', 'en0', 100, 40),
            (1, '2026-11-06T14:00:00+00:00', '2026-11-06T14:00:10+00:00', 'en0', 1000, 1000),
            (2, '2026-11-06T09:00:00+00:00', '2026-11-06T09:00:10+00:00', 'en0', 500, 500),
        ]
        changes = [(1, '2026-11-06T06:30:00+00:00', 'b'),
                   (1, '2026-11-06T07:00:00+00:00', 'a'),
                   (1, '2026-11-06T07:30:00+00:00', 'b'),
                   (1, '2026-11-06T13:00:00+00:00', 'b'),
                   (2, '2026-11-06T08:00:00+00:00', 'c')]
        result = contextual_traffic_usage(intervals, changes,
                                          {'a': 'home', 'b': 'school', 'c': 'other'},
                                          schedule, as_of)
        self.assertEqual(result['school'], [('en0', 550, 520)])
        self.assertEqual(result['home'], [('en0', 100, 10)])
        self.assertEqual(result['school_network'], [('en0', 1000, 100)])
        self.assertEqual(result['other_network'], [('en0', 500, 500)])
        self.assertTrue(result['schedule_configured'])
        self.assertFalse(result['schedule_uncertain'])

    def test_contextual_traffic_marks_ambiguous_school_boundaries(self):
        schedule = {'timezone': 'Europe/Vienna', 'days': [6], 'start': '02:30', 'end': '03:30'}
        intervals = [(1, '2026-10-25T00:25:00+00:00', '2026-10-25T00:35:00+00:00', 'en0', 100, 50)]
        result = contextual_traffic_usage(intervals, [], {}, schedule,
                                          datetime(2026, 10, 25, 2, tzinfo=timezone.utc))
        self.assertEqual(result['school'], [])
        self.assertTrue(result['schedule_uncertain'])


    def test_system_local_fallback_splits_at_host_midnight(self):
        local_day = datetime.now().astimezone().date()
        boundary = _system_local_midnight_utc(local_day)
        rows = [
            ('s', (boundary - timedelta(seconds=15)).isoformat(), 'App', 'app'),
            ('s', (boundary + timedelta(seconds=15)).isoformat(), 'App', 'app'),
        ]
        result = estimates(rows, boundary + timedelta(seconds=16), calendar_timezone=None)
        self.assertEqual(result['today'], [('App', 15.0)])
        self.assertEqual(result['week'], [('App', 30.0)])

    @unittest.skipUnless(hasattr(time, 'tzset'), 'host time-zone override requires tzset')
    def test_system_local_fallback_uses_operating_system_dst_rules(self):
        old_tz = os.environ.get('TZ')
        try:
            os.environ['TZ'] = 'Europe/Vienna'
            time.tzset()
            rows = [
                ('s', '2026-03-28T22:59:30+00:00', 'App', 'app'),
                ('s', '2026-03-28T23:00:00+00:00', 'App', 'app'),
                ('s', '2026-03-28T23:00:30+00:00', 'App', 'app'),
            ]
            result = estimates(rows, datetime(2026, 3, 29, 1, 30, tzinfo=timezone.utc),
                               calendar_timezone=None)
            self.assertEqual(result['today'], [('App', 30.0)])
            self.assertEqual(result['week'], [('App', 60.0)])
        finally:
            if old_tz is None:
                os.environ.pop('TZ', None)
            else:
                os.environ['TZ'] = old_tz
            time.tzset()

    def test_excludes_unknown_switch_gap_and_cross_session(self):
        rows = [(1, '2026-11-07T12:00:00+00:00', 'App', 'app'),
                (1, '2026-11-07T12:00:15+00:00', 'App', 'app'),
                (1, '2026-11-07T12:00:30+00:00', None, None),
                (1, '2026-11-07T12:00:45+00:00', 'App', 'app'),
                (1, '2026-11-07T12:01:45+00:00', 'App', 'app'),
                (2, '2026-11-07T12:02:00+00:00', 'App', 'app'),
                (2, '2026-11-07T12:02:15+00:00', 'Other', 'other')]
        result = estimates(rows, datetime(2026, 11, 7, 13, tzinfo=timezone.utc))
        self.assertEqual(result['today'], [('App', 15)])
        self.assertEqual(result['week'], [('App', 15)])

    def test_splits_at_utc_midnight(self):
        rows = [(1, '2026-11-06T23:59:50+00:00', 'App', 'app'),
                (1, '2026-11-07T00:00:10+00:00', 'App', 'app')]
        result = estimates(rows, datetime(2026, 11, 7, 1, tzinfo=timezone.utc))
        self.assertEqual(result['today'], [('App', 10)])
        self.assertEqual(result['week'], [('App', 20)])

    def test_splits_daily_report_at_selected_local_midnight(self):
        zone = ZoneInfo('Europe/Vienna')
        rows = [(1, '2026-01-01T22:59:50+00:00', 'App', 'app'),
                (1, '2026-01-01T23:00:10+00:00', 'App', 'app')]
        result = estimates(rows, datetime(2026, 1, 2, 0, 30, tzinfo=zone), calendar_timezone=zone)
        self.assertEqual(result['today'], [('App', 10)])
        self.assertEqual(result['week'], [('App', 20)])

    def test_seven_day_window_starts_at_local_midnight_across_dst_change(self):
        zone = ZoneInfo('Europe/Vienna')
        rows = [(1, '2026-03-22T22:59:50+00:00', 'App', 'app'),
                (1, '2026-03-22T23:00:10+00:00', 'App', 'app')]
        result = estimates(rows, datetime(2026, 3, 29, 1, 30, tzinfo=timezone.utc),
                           calendar_timezone=zone)
        self.assertEqual(result['today'], [])
        self.assertEqual(result['week'], [('App', 10)])

    def test_agent_runtime_clips_window_merges_sessions_and_excludes_known_gaps(self):
        as_of = datetime(2026, 11, 7, 10, tzinfo=timezone.utc)
        sessions = [
            ('2026-11-07T09:00:00+00:00', '2026-11-07T10:00:00+00:00', '2026-11-07T10:00:00+00:00'),
            ('2026-11-07T09:10:00+00:00', '2026-11-07T09:50:00+00:00', '2026-11-07T09:50:00+00:00'),
            ('Start unavailable', '2026-11-07T09:45:00+00:00', None),
        ]
        gaps = [
            ('2026-11-07T09:20:00+00:00', '2026-11-07T09:30:00+00:00'),
            ('2026-11-07T09:25:00+00:00', '2026-11-07T09:35:00+00:00'),
            ('2026-10-29T08:00:00+00:00', '2026-10-29T08:05:00+00:00'),
        ]
        self.assertEqual(agent_runtime(sessions, gaps, as_of),
                         {'seconds': 2700.0, 'sessions': 2, 'gaps': 2, 'days': 7})

    def test_agent_runtime_rejects_naive_reference_and_handles_empty_report(self):
        with self.assertRaises(ValueError):
            agent_runtime([], [], datetime(2026, 11, 7))
        self.assertEqual(agent_runtime([], [], datetime(2026, 11, 7, tzinfo=timezone.utc)),
                         {'seconds': 0.0, 'sessions': 0, 'gaps': 0, 'days': 7})
