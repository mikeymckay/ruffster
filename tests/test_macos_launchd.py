import plistlib
import unittest
from family_activity.macos_launchd import agent_plist

class MacLaunchdTests(unittest.TestCase):
    def test_encrypted_agent_launches_at_login_and_restarts(self):
        plist = plistlib.loads(agent_plist('org.example.family', '/usr/bin/python3', '/opt/family', '/tmp/db file', '/tmp/key', '/tmp/fg', '/tmp/status'))
        self.assertTrue(plist['RunAtLoad'])
        self.assertTrue(plist['KeepAlive'])
        self.assertEqual(plist['LimitLoadToSessionType'], 'Aqua')
        self.assertIn('/tmp/db file', plist['ProgramArguments'])
        self.assertIn('--experimental-public-key', plist['ProgramArguments'])
        self.assertIn('--experimental-network', plist['ProgramArguments'])
        self.assertIn('--experimental-network-settings', plist['ProgramArguments'])
        self.assertEqual(plist['ProgramArguments'][plist['ProgramArguments'].index('--retention-days') + 1], '30')
        self.assertNotIn('--experimental-private-key', plist['ProgramArguments'])

    def test_rejects_relative_paths_and_unsafe_label(self):
        with self.assertRaises(ValueError):
            agent_plist('unsafe/label', '/usr/bin/python3', '/opt/family', '/tmp/db', '/tmp/key', '/tmp/fg', '/tmp/status')
        with self.assertRaises(ValueError):
            agent_plist('org.example', 'python3', '/opt/family', '/tmp/db', '/tmp/key', '/tmp/fg', '/tmp/status')

    def test_frozen_agent_has_direct_entrypoint(self):
        plist = plistlib.loads(agent_plist('org.example.frozen', '/tmp/FamilyActivityCore', '/tmp/runtime', '/tmp/db', '/tmp/key', '/tmp/fg', '/tmp/status', frozen=True))
        self.assertEqual(plist['ProgramArguments'][:2], ['/tmp/FamilyActivityCore', 'agent'])
        self.assertNotIn('-m', plist['ProgramArguments'])

    def test_optional_network_identity_key_is_passed_to_agent(self):
        args = plistlib.loads(agent_plist('org.example.network', '/usr/bin/python3', '/opt/family',
                                          '/tmp/db', '/tmp/key', '/tmp/fg', '/tmp/status',
                                          network_key='/tmp/network.key'))['ProgramArguments']
        self.assertIn('--experimental-network-key', args)
        self.assertEqual(args[args.index('--experimental-network-key') + 1], '/tmp/network.key')

    def test_synthetic_validation_can_disable_network_observations(self):
        args = plistlib.loads(agent_plist(
            'org.example.synthetic', '/usr/bin/python3', '/opt/family', '/tmp/db', '/tmp/key',
            '/tmp/fg', '/tmp/status', collect_network=False,
            collect_network_settings=False))['ProgramArguments']
        self.assertNotIn('--experimental-network', args)
        self.assertNotIn('--experimental-network-settings', args)
        self.assertNotIn('--experimental-network-key', args)

    def test_rejects_network_settings_without_network_collection(self):
        with self.assertRaisesRegex(ValueError, 'requires network collection'):
            agent_plist('org.example', '/usr/bin/python3', '/opt/family', '/tmp/db', '/tmp/key',
                        '/tmp/fg', '/tmp/status', collect_network=False)

    def test_retention_must_be_an_available_choice(self):
        with self.assertRaises(ValueError):
            agent_plist('org.example', '/usr/bin/python3', '/opt/family', '/tmp/db', '/tmp/key', '/tmp/fg', '/tmp/status', retention_days=14)
