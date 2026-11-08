import unittest
from family_activity.macos import parse_netstat, traffic_delta

SAMPLE = '''Name Mtu Network Address Ipkts Ierrs Ibytes Opkts Oerrs Obytes Coll
lo0 16384 <Link#1> 100 0 1000 100 0 1000 0
en0 1500 <Link#2> aa:bb:cc:dd:ee:ff 100 0 10000 200 0 20000 0
en0 1500 192.168.1 192.168.1.2 100 - 10000 200 - 20000 -
utun0* 1500 <Link#3> 10 0 300 11 0 400 0
'''

class MacNetworkTests(unittest.TestCase):
    def test_only_one_link_row_per_non_loopback_interface(self):
        self.assertEqual(parse_netstat(SAMPLE), {'en0': (10000, 20000), 'utun0': (300, 400)})

    def test_malformed_output_is_unknown(self):
        self.assertEqual(parse_netstat('unexpected'), {})

    def test_reset_and_new_interfaces_are_not_invented(self):
        before = {'en0': (10, 20), 'utun0': (100, 100)}
        after = {'en0': (20, 25), 'utun0': (2, 1), 'en1': (10, 10)}
        self.assertEqual(traffic_delta(before, after), {'en0': (10, 5)})

class ForegroundTests(unittest.TestCase):
    def test_native_helper_reads_app_identity_without_window_content(self):
        from pathlib import Path
        source = (Path(__file__).parents[1] / 'native/macos/foreground.swift').read_text(encoding='utf-8')
        self.assertIn('app.localizedName', source)
        self.assertIn('app.bundleIdentifier', source)
        for window_detail_api in ('GetWindowText', 'window.title', 'windowTitle',
                                  'CGWindowListCopyWindowInfo', 'kCGWindowName'):
            with self.subTest(api=window_detail_api):
                self.assertNotIn(window_detail_api, source)

    def test_helper_success_and_invalid_output(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from family_activity.macos import foreground_application
        with patch('family_activity.macos.subprocess.run', return_value=SimpleNamespace(stdout='{"name":"Finder","bundle_id":"com.apple.finder"}')):
            self.assertEqual(foreground_application('/helper'), ('Finder', 'com.apple.finder'))
        for output in ('null', '{}', 'not json', '{"name": 3, "bundle_id": "x"}'):
            with self.subTest(output=output), patch('family_activity.macos.subprocess.run', return_value=SimpleNamespace(stdout=output)):
                self.assertIsNone(foreground_application('/helper'))
