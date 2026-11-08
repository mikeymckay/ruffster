import unittest
from family_activity.network_identity import identifier, parse_route, parse_router_mac

class IdentityTests(unittest.TestCase):
    def test_route_and_arp(self):
        route = ' route to: default\n gateway: 192.0.2.1\n interface: en0\n'
        self.assertEqual(parse_route(route), ('192.0.2.1', 'en0'))
        self.assertEqual(parse_router_mac('? (192.0.2.1) at 0:a:B:c:d:ef on en0', '192.0.2.1'), '00:0a:0b:0c:0d:ef')
        self.assertIsNone(parse_router_mac('? (192.0.2.2) at 0:a:b:c:d:ef on en0', '192.0.2.1'))
        self.assertIsNone(parse_router_mac('? (192.0.2.1) at (incomplete) on en0', '192.0.2.1'))

    def test_missing_and_invalid_route_are_unknown(self):
        for text in ('', 'gateway: link#1\ninterface: en0', 'gateway: 192.0.2.1\ninterface: en0;bad'):
            self.assertIsNone(parse_route(text))

    def test_hmac_is_device_specific(self):
        a = identifier(b'a'*32, '00:11:22:33:44:55')
        self.assertEqual(a, identifier(b'a'*32, '00:11:22:33:44:55'))
        self.assertNotEqual(a, identifier(b'b'*32, '00:11:22:33:44:55'))
        with self.assertRaises(ValueError): identifier(b'short', '00:11:22:33:44:55')
