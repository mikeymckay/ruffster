from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from nacl.public import PrivateKey
from family_activity.school_schedule import load, overlap, save, validate
from family_activity.reports import contextual_estimates

class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.schedule = {'timezone':'Europe/Vienna', 'days':[0,1,2,3,4], 'start':'09:00', 'end':'15:00'}

    def test_encrypted_settings_and_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            key = PrivateKey.generate(); path=Path(tmp)/'schedule'
            save(path, key, self.schedule)
            self.assertEqual(load(path, key), self.schedule)
            self.assertNotIn(b'Europe/Vienna', path.read_bytes())
            with self.assertRaises(ValueError): validate({**self.schedule, 'end':'08:00'})
            with self.assertRaises(ValueError): validate({**self.schedule, 'timezone':'Invalid/Zone'})
            self.assertEqual(load(path, key), self.schedule)

    def test_school_and_home_overlap_are_independent(self):
        samples=[(1,at,'App','app') for at in (
            '2026-11-02T07:59:40+00:00','2026-11-02T07:59:50+00:00',
            '2026-11-02T08:00:00+00:00','2026-11-02T08:00:10+00:00',
            '2026-11-02T08:00:20+00:00','2026-11-02T08:00:30+00:00')]
        changes=[(1,'2026-11-02T07:59:35+00:00','home-token'),
                 (1,'2026-11-02T08:00:00+00:00','school-token'),
                 (1,'2026-11-02T08:00:20+00:00','other-token')]
        result=contextual_estimates(samples, changes,
                                    {'home-token':'home','school-token':'school','other-token':'other'},
                                    self.schedule, datetime(2026,11,2,9,tzinfo=timezone.utc))
        self.assertEqual(result['school'], [('App',30)])
        self.assertEqual(result['home'], [('App',10)])
        self.assertEqual(result['school_network'], [('App',10)])
        self.assertEqual(result['other_network'], [('App',10)])
        self.assertFalse(result['schedule_uncertain'])
        self.assertEqual(contextual_estimates(samples, [], {}, None, datetime(2026,11,2,9,tzinfo=timezone.utc))['home'], [])

    def test_ambiguous_daylight_saving_boundary_is_unknown(self):
        schedule={'timezone':'Europe/Vienna','days':[6],'start':'02:15','end':'03:15'}
        start=datetime(2026,10,25,1,0,tzinfo=timezone.utc)
        end=datetime(2026,10,25,1,0,20,tzinfo=timezone.utc)
        self.assertEqual(overlap(start,end,schedule),(0.0,True))
