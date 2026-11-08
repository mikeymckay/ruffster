import unittest
from unittest.mock import patch, MagicMock
import sys
from types import SimpleNamespace
from family_activity.network_settings import (
    parse_dns, parse_proxy, parse_vpn, parse_windows_vpn, observe_macos,
    observe_windows, observe_windows_vpn,
)

class NetworkSettingsTests(unittest.TestCase):
    def test_dns_only_reports_resolver_presence(self):
        self.assertTrue(parse_dns('DNS configuration\n nameserver[0] : 192.0.2.7\n'))
        self.assertTrue(parse_dns('DNS configuration\n nameserver[1] : fe80::1%en0\n'))
        self.assertFalse(parse_dns('DNS configuration\n resolver #1\n'))
        self.assertIsNone(parse_dns('unexpected output'))

    def test_proxy_unknown_and_enabled_flags(self):
        self.assertTrue(parse_proxy('HTTPEnable : 1\nHTTPProxy : private.example\n'))
        self.assertFalse(parse_proxy('HTTPEnable : 0\nSOCKSEnable : 0\n'))
        self.assertIsNone(parse_proxy('ProxyAutoConfigURLString : https://private.example/file\n'))
        self.assertIsNone(parse_proxy('HTTPEnable : maybe\n'))

    def test_vpn_presence_not_absence(self):
        self.assertTrue(parse_vpn('* (Connected) synthetic profile'))
        self.assertIsNone(parse_vpn('* (Disconnected) synthetic profile'))
        self.assertIsNone(parse_vpn(None))

    def test_windows_vpn_parser_accepts_only_status_tokens(self):
        self.assertTrue(parse_windows_vpn('connected\n'))
        self.assertFalse(parse_windows_vpn('disconnected\n'))
        self.assertIsNone(parse_windows_vpn('Connected: private profile'))
        self.assertIsNone(parse_windows_vpn('unknown'))
        self.assertIsNone(parse_windows_vpn(None))

    def test_windows_vpn_probe_returns_only_minimized_status(self):
        with patch('family_activity.network_settings.subprocess.run',
                   return_value=SimpleNamespace(stdout='connected\n')) as run:
            self.assertTrue(observe_windows_vpn())
        command = run.call_args.args[0]
        script = command[-1]
        self.assertIn('Get-VpnConnection -AllUserConnection', script)
        self.assertNotIn('Private VPN Name', script)
        self.assertEqual(run.call_args.kwargs['timeout'], 5)

    def test_windows_vpn_probe_errors_are_unknown(self):
        with patch('family_activity.network_settings.subprocess.run', side_effect=OSError('unavailable')):
            self.assertIsNone(observe_windows_vpn())

    def test_windows_vpn_script_reports_status_without_profile_details(self):
        import os
        import shutil
        import subprocess
        from family_activity.network_settings import _WINDOWS_VPN_SCRIPT
        shell = shutil.which('pwsh') or shutil.which('powershell.exe')
        if not shell:
            self.skipTest('PowerShell is required to run the mocked VPN profile probe')
        prefix = r'''
function Get-VpnConnection {
    param([switch]$AllUserConnection)
    if ($env:FAMILY_ACTIVITY_TEST_VPN_MODE -eq 'connected' -and !$AllUserConnection) {
        [pscustomobject]@{Name='SECRET_PROFILE_NAME';ConnectionStatus='Connected'}
    } elseif ($env:FAMILY_ACTIVITY_TEST_VPN_MODE -eq 'error' -and $AllUserConnection) {
        throw 'PRIVATE_ERROR_TEXT'
    }
}
'''
        for mode, expected in (('connected', 'connected'), ('disconnected', 'disconnected'),
                               ('error', 'unknown')):
            environment = os.environ.copy()
            environment['FAMILY_ACTIVITY_TEST_VPN_MODE'] = mode
            result = subprocess.run([shell, '-NoLogo', '-NoProfile', '-Command',
                                     prefix + _WINDOWS_VPN_SCRIPT], capture_output=True,
                                    text=True, timeout=10, env=environment, check=True)
            self.assertEqual(result.stdout.strip(), expected)
            self.assertNotIn('SECRET_PROFILE_NAME', result.stdout)
            self.assertNotIn('PRIVATE_ERROR_TEXT', result.stdout)

    def test_no_addresses_or_names_returned(self):
        outputs=[SimpleNamespace(stdout='DNS configuration\n nameserver[0] : 192.0.2.1\n'),
                 SimpleNamespace(stdout='HTTPEnable : 1\nHTTPProxy : secret.example\n'),
                 SimpleNamespace(stdout='* (Connected) Private VPN Name\n')]
        with patch('family_activity.network_settings.subprocess.run', side_effect=outputs):
            self.assertEqual(observe_macos(),{'dns_observed':True,'proxy_indicator':True,'vpn_indicator':True})

    def test_windows_returns_only_minimized_registry_indicators(self):
        # Mimic two network adapters and Internet Settings. Sensitive values are
        # supplied but should never appear in the returned record.
        winreg = MagicMock()
        winreg.HKEY_LOCAL_MACHINE = object()
        winreg.HKEY_CURRENT_USER = object()
        def key_for(path):
            key = MagicMock()
            key.__enter__.return_value = key
            if path.endswith('Interfaces'):
                key.family = 'v6' if 'Tcpip6' in path else 'v4'
                winreg.QueryInfoKey.return_value = (2, 0, 0)
            elif path.endswith('adapter-a') or path.endswith('adapter-v6'):
                key.query = lambda field: {'NameServer': ('2001:db8::53', 1)}[field] if path.endswith('adapter-v6') and field == 'NameServer' else (_ for _ in ()).throw(OSError('missing'))
            elif path.endswith('adapter-b') or path.endswith('adapter-v6-b'):
                key.query = lambda field: {'DhcpNameServer': ('2001:db8::1', 1)}[field] if path.endswith('adapter-v6-b') and field == 'DhcpNameServer' else (_ for _ in ()).throw(OSError('missing'))
            else:
                key.query = lambda field: {'ProxyEnable': (1, 4), 'AutoDetect': (0, 4),
                                            'AutoConfigURL': ('https://private.example/pac', 1)}[field]
            return key
        winreg.OpenKey.side_effect = lambda root, path: key_for(path)
        winreg.EnumKey.side_effect = lambda key, index: (('adapter-v6', 'adapter-v6-b') if key.family == 'v6' else ('adapter-a', 'adapter-b'))[index]
        winreg.QueryValueEx.side_effect = lambda key, field: key.query(field)
        with patch.dict(sys.modules, {'winreg': winreg}), patch(
                'family_activity.network_settings.subprocess.run',
                return_value=SimpleNamespace(stdout='connected\n')):
            result = observe_windows()
        self.assertEqual(result, {'dns_observed': True, 'proxy_indicator': True, 'vpn_indicator': True})
        self.assertNotIn('private.example', repr(result))

    def test_windows_unknown_when_registry_unavailable(self):
        winreg = MagicMock()
        winreg.HKEY_LOCAL_MACHINE = object()
        winreg.HKEY_CURRENT_USER = object()
        winreg.OpenKey.side_effect = OSError('unavailable')
        with patch.dict(sys.modules, {'winreg': winreg}), patch(
                'family_activity.network_settings.subprocess.run', side_effect=OSError('unavailable')):
            result = observe_windows()
        self.assertEqual(result, {'dns_observed': None, 'proxy_indicator': None, 'vpn_indicator': None})
