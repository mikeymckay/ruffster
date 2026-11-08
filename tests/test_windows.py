import shutil
import sys
import types
import unittest
from unittest.mock import patch
from family_activity import windows


def _powershell_executable():
    if sys.platform == 'win32':
        import os
        from pathlib import Path
        native = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
        if native.is_file():
            return str(native)
        return shutil.which('powershell') or shutil.which('pwsh')
    return shutil.which('pwsh')


class WindowsAdapterTests(unittest.TestCase):
    def test_foreground_adapter_never_reads_window_titles(self):
        import inspect
        source = inspect.getsource(windows.foreground_application)
        self.assertNotIn('GetWindowText', source)
        self.assertNotIn('GetWindowTextLength', source)
        self.assertIn('ntpath.basename(buf.value)', source)

    @unittest.skipUnless(_powershell_executable(), 'requires PowerShell')
    def test_default_route_script_parses_in_powershell(self):
        import os
        import subprocess
        import tempfile
        from pathlib import Path
        powershell = _powershell_executable()
        with tempfile.TemporaryDirectory() as tmp:
            script_path = Path(tmp) / 'router-hint.ps1'
            script_path.write_text(windows._DEFAULT_ROUTE_SCRIPT, encoding='utf-8')
            env = os.environ.copy()
            env['FAMILY_ACTIVITY_PS_SCRIPT'] = str(script_path)
            parser = ("$tokens=$null; $errors=$null; "
                      "$null=[System.Management.Automation.Language.Parser]::ParseFile($env:FAMILY_ACTIVITY_PS_SCRIPT,[ref]$tokens,[ref]$errors); "
                      "if ($errors.Count -gt 0) { $errors | ForEach-Object { [Console]::Error.WriteLine($_.Message) }; exit 1 }")
            result = subprocess.run([powershell, '-NoLogo', '-NoProfile', '-NonInteractive',
                                     '-Command', parser], env=env, capture_output=True, text=True,
                                    timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(_powershell_executable(), 'requires PowerShell')
    def test_windows_preview_builder_parses_in_powershell(self):
        import os
        import subprocess
        from pathlib import Path
        powershell = _powershell_executable()
        script_path = Path(__file__).parents[1] / 'scripts' / 'build-windows-preview.ps1'
        env = os.environ.copy()
        env['FAMILY_ACTIVITY_PS_SCRIPT'] = str(script_path)
        parser = ("$tokens=$null; $errors=$null; "
                  "$null=[System.Management.Automation.Language.Parser]::ParseFile($env:FAMILY_ACTIVITY_PS_SCRIPT,[ref]$tokens,[ref]$errors); "
                  "if ($errors.Count -gt 0) { $errors | ForEach-Object { [Console]::Error.WriteLine($_.Message) }; exit 1 }")
        result = subprocess.run([powershell, '-NoLogo', '-NoProfile', '-NonInteractive',
                                 '-Command', parser], env=env, capture_output=True, text=True,
                                timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(_powershell_executable(), 'requires PowerShell')
    def test_default_route_script_selects_lowest_combined_metric_with_mock_tables(self):
        import os
        import subprocess
        import tempfile
        from pathlib import Path
        powershell = _powershell_executable()
        harness = r"""
function Get-NetIPInterface {
    [CmdletBinding()]
    param([string]$AddressFamily)
    [pscustomobject]@{ InterfaceIndex = 12; InterfaceMetric = 100 }
    [pscustomobject]@{ InterfaceIndex = 13; InterfaceMetric = 5 }
}
function Get-NetRoute {
    [CmdletBinding()]
    param([string]$AddressFamily, [string]$DestinationPrefix)
    if ($AddressFamily -eq 'IPv4') {
        [pscustomobject]@{ InterfaceIndex = 12; RouteMetric = 1; DestinationPrefix = '0.0.0.0/0'; NextHop = '192.0.2.1' }
        [pscustomobject]@{ InterfaceIndex = 13; RouteMetric = 50; DestinationPrefix = '0.0.0.0/0'; NextHop = '198.51.100.1' }
    }
}
function Get-NetNeighbor {
    [CmdletBinding()]
    param([string]$AddressFamily, [uint32]$InterfaceIndex, [string]$IPAddress)
    if ($AddressFamily -eq 'IPv4' -and $IPAddress -eq '192.0.2.1') {
        [pscustomobject]@{ State = 'Reachable'; LinkLayerAddress = '00-11-22-33-44-55' }
    } elseif ($AddressFamily -eq 'IPv4' -and $IPAddress -eq '198.51.100.1') {
        [pscustomobject]@{ State = 'Stale'; LinkLayerAddress = '00-22-33-44-55-66' }
    }
}
& ([scriptblock]::Create([IO.File]::ReadAllText($env:FAMILY_ACTIVITY_PS_SCRIPT)))
"""
        with tempfile.TemporaryDirectory() as tmp:
            script_path = Path(tmp) / 'router-hint.ps1'
            harness_path = Path(tmp) / 'test-router-hint.ps1'
            script_path.write_text(windows._DEFAULT_ROUTE_SCRIPT, encoding='utf-8')
            harness_path.write_text(harness, encoding='utf-8')
            env = os.environ.copy()
            env['FAMILY_ACTIVITY_PS_SCRIPT'] = str(script_path)
            result = subprocess.run([powershell, '-NoLogo', '-NoProfile', '-NonInteractive',
                                     '-ExecutionPolicy', 'Bypass', '-File', str(harness_path)],
                                    env=env, capture_output=True, text=True, timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '00-22-33-44-55-66')

    @unittest.skipUnless(_powershell_executable(), 'requires PowerShell')
    def test_default_route_script_finds_gateway_on_ipv6_only_network(self):
        import os
        import subprocess
        import tempfile
        from pathlib import Path
        powershell = _powershell_executable()
        harness = r"""
function Get-NetIPInterface {
    [CmdletBinding()]
    param([string]$AddressFamily)
    if ($AddressFamily -eq 'IPv6') {
        [pscustomobject]@{ InterfaceIndex = 7; InterfaceMetric = 20 }
    }
}
function Get-NetRoute {
    [CmdletBinding()]
    param([string]$AddressFamily)
    if ($AddressFamily -eq 'IPv6') {
        [pscustomobject]@{ InterfaceIndex = 7; RouteMetric = 10; DestinationPrefix = '::/0'; NextHop = 'fe80::1%7' }
    }
}
function Get-NetNeighbor {
    [CmdletBinding()]
    param([string]$AddressFamily, [uint32]$InterfaceIndex, [string]$IPAddress)
    if ($AddressFamily -eq 'IPv6' -and $IPAddress -eq 'fe80::1%7') {
        [pscustomobject]@{ State = 'Stale'; LinkLayerAddress = '00-33-44-55-66-77' }
    }
}
& ([scriptblock]::Create([IO.File]::ReadAllText($env:FAMILY_ACTIVITY_PS_SCRIPT)))
"""
        with tempfile.TemporaryDirectory() as tmp:
            script_path = Path(tmp) / 'router-hint.ps1'
            harness_path = Path(tmp) / 'test-ipv6-router-hint.ps1'
            script_path.write_text(windows._DEFAULT_ROUTE_SCRIPT, encoding='utf-8')
            harness_path.write_text(harness, encoding='utf-8')
            env = os.environ.copy()
            env['FAMILY_ACTIVITY_PS_SCRIPT'] = str(script_path)
            result = subprocess.run([powershell, '-NoLogo', '-NoProfile', '-NonInteractive',
                                     '-ExecutionPolicy', 'Bypass', '-File', str(harness_path)],
                                    env=env, capture_output=True, text=True, timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '00-33-44-55-66-77')

    def test_windows_router_mac_is_pseudonymized_and_invalid_neighbors_are_unknown(self):
        import subprocess
        from family_activity.network_identity import identifier
        self.assertEqual(windows.parse_gateway_mac('00-11-22-33-44-55'), '00:11:22:33:44:55')
        for output in ('', '00:11:22:33:44:55\nff:ff:ff:ff:ff:ff',
                       '00:00:00:00:00:00', '01:11:22:33:44:55', '192.0.2.1'):
            with self.subTest(output=output):
                self.assertIsNone(windows.parse_gateway_mac(output))
        raw_mac = '00-11-22-33-44-55\r\n'
        result = subprocess.CompletedProcess([], 0, raw_mac, '')
        with patch.object(windows.sys, 'platform', 'win32'), \
             patch.object(windows.subprocess, 'run', return_value=result) as run:
            value = windows.network_identifier(b'n' * 32)
        self.assertEqual(value, identifier(b'n' * 32, '00:11:22:33:44:55'))
        self.assertNotIn('00-11-22-33-44-55', value)
        self.assertEqual(run.call_args.args[0][-1], windows._DEFAULT_ROUTE_SCRIPT)
        self.assertEqual(run.call_args.kwargs['timeout'], 5)
        self.assertIn('Get-NetIPInterface', windows._DEFAULT_ROUTE_SCRIPT)
        self.assertIn('RouteMetric + $metric', windows._DEFAULT_ROUTE_SCRIPT)
        self.assertIn("@('IPv4', 'IPv6')", windows._DEFAULT_ROUTE_SCRIPT)
        self.assertIn("$_.DestinationPrefix -eq '::/0'", windows._DEFAULT_ROUTE_SCRIPT)

        with patch.object(windows.sys, 'platform', 'win32'), \
             patch.object(windows.subprocess, 'run', side_effect=subprocess.TimeoutExpired('powershell.exe', 5)):
            self.assertIsNone(windows.network_identifier(b'n' * 32))

    def test_windowed_frozen_entrypoint_supports_cli_without_console_streams(self):
        import subprocess
        from pathlib import Path
        code = ("import runpy,sys; sys.argv=['FamilyActivityCore','--help']; "
                "sys.stdout=None; sys.stderr=None; runpy.run_path('scripts/frozen_main.py',run_name='__main__')")
        result = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).parents[1],
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b'')

    def test_unsupported_platform_reports_unknown(self):
        with patch.object(windows.sys, 'platform', 'linux'):
            self.assertIsNone(windows.foreground_application())
            self.assertIsNone(windows.network_counters())

    def test_windows_counters_preserve_raw_resets(self):
        calls = []
        def counters(**kwargs):
            calls.append(kwargs)
            return {'Ethernet': types.SimpleNamespace(bytes_recv=123, bytes_sent=456)}
        fake = types.SimpleNamespace(net_io_counters=counters)
        with patch.object(windows.sys, 'platform', 'win32'), patch.dict(sys.modules, {'psutil': fake}):
            self.assertEqual(windows.network_counters(), {'Ethernet': (123, 456)})
        self.assertEqual(calls, [{'pernic': True, 'nowrap': False}])

    def test_foreground_returns_only_process_basename_and_closes_handle(self):
        import ctypes
        from unittest.mock import patch
        from family_activity import windows
        class ApiCall:
            def __init__(self, callback): self.callback = callback
            def __call__(self, *args): return self.callback(*args)
        closed=[]
        def process_id(hwnd,pid):
            pid._obj.value=321
            return 7
        user=types.SimpleNamespace(
            GetForegroundWindow=ApiCall(lambda: 100),
            GetWindowThreadProcessId=ApiCall(process_id),
        )
        def image_name(handle,flags,buffer,length):
            self.assertEqual((handle,flags),(12,0))
            buffer.value=r'C:\Program Files\Family Activity\study.exe'
            length._obj.value=len(buffer.value)
            return 1
        kernel=types.SimpleNamespace(
            OpenProcess=ApiCall(lambda access,inherit,pid: 12 if (access,inherit,pid)==(0x1000,False,321) else 0),
            QueryFullProcessImageNameW=ApiCall(image_name),
            CloseHandle=ApiCall(lambda handle: closed.append(handle) or 1),
        )
        with patch.object(windows.sys,'platform','win32'), \
             patch.object(ctypes,'WinDLL',create=True,side_effect=lambda name,**kwargs: {'user32':user,'kernel32':kernel}[name]):
            result=windows.foreground_application()
        self.assertEqual(result,('study.exe',''))
        self.assertEqual(closed,[12])

class WindowsTaskTests(unittest.TestCase):
    def test_manifest_escapes_paths_and_has_bounded_restart(self):
        import xml.etree.ElementTree as ET
        from family_activity.windows_task import task_xml
        xml = task_xml('Family\\Child & Co', r'C:\Python\pythonw.exe', r'C:\Activity Data\activity.db', r'C:\Activity Data\parent.pub', r'C:\Activity Data\status.exe', r'C:\App Source')
        root = ET.fromstring(xml)
        ns = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}
        self.assertEqual(root.findtext('t:Settings/t:RestartOnFailure/t:Interval', namespaces=ns), 'PT1M')
        self.assertEqual(root.findtext('t:Settings/t:RestartOnFailure/t:Count', namespaces=ns), '10')
        self.assertEqual(root.findtext('t:Principals/t:Principal/t:UserId', namespaces=ns), 'Family\\Child & Co')
        args = root.findtext('t:Actions/t:Exec/t:Arguments', namespaces=ns)
        self.assertIn('"C:\\Activity Data\\activity.db"', args)
        self.assertIn('--experimental-public-key', args)
        self.assertIn('--retention-days 30', args)
        self.assertEqual(root.findtext('t:Actions/t:Exec/t:WorkingDirectory', namespaces=ns), r'C:\App Source')
        self.assertEqual(root.findtext('t:Principals/t:Principal/t:RunLevel', namespaces=ns), 'LeastPrivilege')
        self.assertEqual(root.findtext('t:Principals/t:Principal/t:LogonType', namespaces=ns), 'InteractiveToken')

    def test_manifest_rejects_unsupported_retention(self):
        from family_activity.windows_task import task_xml
        with self.assertRaises(ValueError):
            task_xml('user',r'C:\Python\pythonw.exe',r'C:\db',r'C:\key',r'C:\status',retention_days=14)

    def test_manifest_rejects_relative_paths(self):
        from family_activity.windows_task import task_xml
        with self.assertRaises(ValueError):
            task_xml('user', 'python.exe', 'db', 'key', 'status')

    def test_manifest_can_pass_private_network_hint_key(self):
        import xml.etree.ElementTree as ET
        from family_activity.windows_task import task_xml, NS
        root = ET.fromstring(task_xml('user', r'C:\Python\pythonw.exe', r'C:\db', r'C:\key',
                                      r'C:\status', network_key=r'C:\data\network.key'))
        args = root.findtext(f"{{{NS}}}Actions/{{{NS}}}Exec/{{{NS}}}Arguments")
        self.assertIn('--experimental-network-key C:\\data\\network.key', args)

    def test_manifest_supports_synthetic_foreground_without_network_collection(self):
        import xml.etree.ElementTree as ET
        from family_activity.windows_task import task_xml, NS
        root = ET.fromstring(task_xml('user', r'C:\Python\FamilyActivityCore.exe', r'C:\data\activity.db',
                                      r'C:\data\parent.pub', r'C:\App\status.exe', r'C:\App', packaged=True,
                                      foreground_helper=r'C:\temp\SyntheticForeground.exe',
                                      monitor_network=False, inspect_network_settings=False))
        args = root.findtext(f"{{{NS}}}Actions/{{{NS}}}Exec/{{{NS}}}Arguments")
        self.assertIn('--experimental-foreground-helper C:\\temp\\SyntheticForeground.exe', args)
        self.assertNotIn('--experimental-windows-foreground', args)
        self.assertNotIn('--experimental-network ', args)
        self.assertNotIn('--experimental-network-settings', args)
        from family_activity import windows_install
        expected = windows_install._identity('user', r'C:\Python\FamilyActivityCore.exe', r'C:\App',
            r'C:\App\status.exe', r'C:\data\activity.db', r'C:\data\parent.pub',
            packaged=True, foreground_helper=r'C:\temp\SyntheticForeground.exe',
            monitor_network=False, inspect_network_settings=False)
        self.assertTrue(windows_install._matching_task(ET.tostring(root, encoding='unicode'), expected))

    def test_manifest_rejects_settings_without_network_sampling(self):
        from family_activity.windows_task import task_xml
        with self.assertRaisesRegex(ValueError, 'require network sampling'):
            task_xml('user', r'C:\Python\pythonw.exe', r'C:\db', r'C:\key', r'C:\status',
                     monitor_network=False, inspect_network_settings=True)

    def test_windows_install_and_uninstall_preserve_encrypted_data(self):
        import json
        import subprocess
        import tempfile
        from pathlib import Path
        from nacl.public import PrivateKey
        from family_activity import public_key_file, windows_install
        from family_activity.encrypted_agent_store import EncryptedAgentStore
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root/'runtime'; package = runtime/'family_activity'
            package.mkdir(parents=True); (package/'__main__.py').write_text('')
            python = root/'pythonw.exe'; python.touch()
            status = root/'FamilyActivityStatus.exe'; status.touch()
            parent = PrivateKey.generate()
            public = root/'family-public.key'; public.write_bytes(public_key_file.encode(parent.public_key))
            calls=[]; registered=[]
            def runner(args):
                calls.append(args)
                if '/Create' in args:
                    xml_path = Path(args[-1]); registered.append(xml_path.read_text(encoding='utf-8'))
                    return subprocess.CompletedProcess(args, 0, '', '')
                if '/Run' in args:
                    return subprocess.CompletedProcess(args, 0, '', '')
                if '/Query' in args and '/XML' in args:
                    return subprocess.CompletedProcess(args, 0 if registered else 1,
                        registered[0] if registered else '', '')
                if '/Query' in args:
                    return subprocess.CompletedProcess(args, 1 if '/Delete' in calls[-1] else 1, '', '')
                if '/Delete' in args:
                    return subprocess.CompletedProcess(args, 0, '', '')
                return subprocess.CompletedProcess(args, 1, '', '')
            with patch.object(windows_install.sys, 'platform', 'win32'):
                result = windows_install.install(public, python, runtime, status, root/'local', user='Child', runner=runner,
                                                readiness_check=lambda *_: True)
                folder=Path(result['data_directory'])
                key_path=folder/'parent.pub'; database=folder/'activity.sqlite3'
                self.assertTrue(key_path.is_file())
                network_key_path=folder/'network.key'
                self.assertEqual(len(network_key_path.read_bytes()),32)
                self.assertTrue((folder/windows_install.METADATA_NAME).is_file())
                self.assertIn('/XML', next(call for call in calls if '/Create' in call))
                self.assertEqual(sum('/Run' in call for call in calls), 1)
                start_call = next(call for call in calls if '/Run' in call)
                self.assertEqual(start_call[-3:], ['/Run', '/TN', windows_install.TASK_NAME])
                self.assertNotIn('/F', next(call for call in calls if '/Create' in call))
                self.assertIn('Family Activity', registered[0])
                self.assertIn('--experimental-network-key', registered[0])
                writer=EncryptedAgentStore(database, parent.public_key, 30)
                writer.event('start'); writer.event('stop'); writer.close()
                removed=[]
                def remove_runner(args):
                    removed.append(args)
                    if '/XML' in args:
                        return subprocess.CompletedProcess(args, 0, registered[0], '')
                    return subprocess.CompletedProcess(args, 0 if any(flag in args for flag in ('/Disable','/End','/Delete')) else 1, '', '')
                outcome=windows_install.uninstall(root/'local', runner=remove_runner)
                self.assertTrue(outcome['task_removed'])
                self.assertTrue(outcome['database_exists'])
                self.assertTrue(outcome['public_key_exists'])
                self.assertTrue(outcome['network_key_exists'])
                self.assertFalse((folder/windows_install.METADATA_NAME).exists())
                db=EncryptedAgentStore(database, parent.public_key, 30); db.close()
                self.assertIn('/Delete', removed[3])

    def test_windows_uninstall_delete_data_removes_router_hint_key(self):
        import json
        import subprocess
        import tempfile
        from pathlib import Path
        from nacl.public import PrivateKey
        from family_activity import public_key_file, windows_install
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); runtime=root/'runtime'; package=runtime/'family_activity'
            package.mkdir(parents=True); (package/'__main__.py').write_text('')
            python=root/'pythonw.exe'; python.touch(); status=root/'status.exe'; status.touch()
            public=root/'public.key'; public.write_bytes(public_key_file.encode(PrivateKey.generate().public_key))
            registered=[]
            def runner(args):
                if '/Create' in args:
                    registered.append(Path(args[-1]).read_text(encoding='utf-8'))
                    return subprocess.CompletedProcess(args,0,'','')
                if '/Run' in args:
                    return subprocess.CompletedProcess(args,0,'','')
                if '/XML' in args:
                    return subprocess.CompletedProcess(args,0 if registered else 1,registered[0] if registered else '','')
                return subprocess.CompletedProcess(args,0 if any(x in args for x in ('/Disable','/End','/Delete')) else 1,'','')
            with patch.object(windows_install.sys,'platform','win32'):
                result=windows_install.install(public,python,runtime,status,root/'local',user='Child',runner=runner,
                                              readiness_check=lambda *_: True)
                folder=Path(result['data_directory']); network_key=folder/'network.key'
                self.assertTrue(network_key.exists())
                outcome=windows_install.uninstall(root/'local',runner=runner,delete_data=True)
            self.assertTrue(outcome['data_deleted'])
            self.assertFalse(network_key.exists())

    def test_packaged_windows_install_registers_frozen_agent_without_python(self):
        import subprocess
        import tempfile
        from pathlib import Path
        from nacl.public import PrivateKey
        from family_activity import public_key_file, windows_install
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); runtime=root/'FamilyActivityCore'; runtime.mkdir()
            core=runtime/'FamilyActivityCore.exe'; core.touch()
            status=root/'FamilyActivitySetup.exe'; status.touch()
            public=root/'family-public.key'; public.write_bytes(public_key_file.encode(PrivateKey.generate().public_key))
            registered=[]
            def runner(args):
                if '/Create' in args:
                    registered.append(Path(args[-1]).read_text(encoding='utf-8'))
                    return subprocess.CompletedProcess(args,0,'','')
                if '/Run' in args:
                    return subprocess.CompletedProcess(args,0,'','')
                if '/XML' in args:
                    return subprocess.CompletedProcess(args,0 if registered else 1,registered[0] if registered else '','')
                return subprocess.CompletedProcess(args,1,'','')
            with patch.object(windows_install.sys,'platform','win32'):
                result=windows_install.install(public,core,root,status,root/'local',user='Child',runner=runner,
                                               packaged=True,readiness_check=lambda *_: True)
            self.assertEqual(Path(result['data_directory']).name,'Family Activity')
            identity=__import__('json').loads((Path(result['data_directory'])/windows_install.METADATA_NAME).read_text())['identity']
            self.assertTrue(identity['packaged'])
            self.assertTrue(windows_install._matching_task(registered[0],identity))
            import xml.etree.ElementTree as ET
            from family_activity.windows_task import NS
            action=ET.fromstring(registered[0]).find(f"{{{NS}}}Actions/{{{NS}}}Exec")
            self.assertEqual(Path(action.findtext(f"{{{NS}}}Command")).resolve(),core.resolve())
            self.assertTrue(action.findtext(f"{{{NS}}}Arguments").startswith('agent --db'))
            self.assertNotIn('-m family_activity',action.findtext(f"{{{NS}}}Arguments"))

    def test_windows_install_can_register_synthetic_helper_without_network_key(self):
        import json
        import subprocess
        import tempfile
        from pathlib import Path
        from nacl.public import PrivateKey
        from family_activity import public_key_file, windows_install
        from family_activity.windows_task import NS
        import xml.etree.ElementTree as ET
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / 'runtime'; package = runtime / 'family_activity'
            package.mkdir(parents=True); (package / '__main__.py').write_text('')
            python = root / 'pythonw.exe'; python.touch()
            status = root / 'status.exe'; status.touch()
            helper = root / 'synthetic-foreground.exe'; helper.touch()
            public = root / 'parent.pub'
            public.write_bytes(public_key_file.encode(PrivateKey.generate().public_key))
            registered = []
            def runner(args):
                if '/Create' in args:
                    registered.append(Path(args[-1]).read_text(encoding='utf-8'))
                    return subprocess.CompletedProcess(args, 0, '', '')
                if '/Run' in args:
                    return subprocess.CompletedProcess(args, 0, '', '')
                if '/XML' in args:
                    return subprocess.CompletedProcess(args, 0 if registered else 1,
                        registered[0] if registered else '', '')
                if '/Query' in args:
                    return subprocess.CompletedProcess(args, 1, '', '')
                return subprocess.CompletedProcess(args, 0, '', '')
            with patch.object(windows_install.sys, 'platform', 'win32'):
                result = windows_install.install(
                    public, python, runtime, status, root / 'local', user='Child', runner=runner,
                    foreground_helper=helper, monitor_network=False, inspect_network_settings=False,
                    readiness_check=lambda *_: True)
            folder = Path(result['data_directory'])
            identity = json.loads((folder / windows_install.METADATA_NAME).read_text())['identity']
            arguments = ET.fromstring(registered[0]).findtext(f"{{{NS}}}Actions/{{{NS}}}Exec/{{{NS}}}Arguments")
            self.assertEqual(identity['foreground_helper'], str(helper.resolve()))
            self.assertFalse(identity['monitor_network'])
            self.assertFalse(identity['inspect_network_settings'])
            self.assertFalse((folder / 'network.key').exists())
            self.assertIn('--experimental-foreground-helper', arguments)
            self.assertNotIn('--experimental-network', arguments)
            self.assertNotIn('--experimental-windows-foreground', arguments)
            self.assertTrue(windows_install._matching_task(registered[0], identity))

    def test_windows_agent_lock_probe_treats_locked_database_as_running(self):
        import tempfile
        from pathlib import Path
        from family_activity import windows_install
        with tempfile.TemporaryDirectory() as tmp:
            database=Path(tmp)/'activity.sqlite3'; lock=Path(str(database)+'.lock'); lock.touch()
            with patch.object(windows_install.locking,'lock_file',side_effect=BlockingIOError):
                self.assertTrue(windows_install._agent_running(database))
            with patch.object(windows_install.locking,'lock_file',return_value=None):
                self.assertFalse(windows_install._agent_running(database))

    def test_windows_readiness_requires_a_new_encrypted_event_and_live_agent(self):
        import tempfile
        from pathlib import Path
        from nacl.public import PrivateKey
        from family_activity import windows_install
        from family_activity.encrypted_agent_store import EncryptedAgentStore
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / 'activity.sqlite3'
            writer = EncryptedAgentStore(database, PrivateKey.generate().public_key, 30)
            writer.event('start')
            previous_count = windows_install._retained_event_count(database)
            writer.event('tick', application=['Synthetic Study App', 'org.example.synthetic-study'])
            writer.close()
            with patch.object(windows_install, '_agent_running', return_value=True):
                self.assertTrue(windows_install._wait_for_ready_session(database, previous_count, timeout=0.1))
                self.assertFalse(windows_install._wait_for_ready_session(database, previous_count + 1, timeout=0.01))
            with patch.object(windows_install, '_agent_running', return_value=False):
                self.assertFalse(windows_install._wait_for_ready_session(database, previous_count, timeout=0.01))

    def test_windows_install_rejects_a_redirected_agent_lock_before_task_registration(self):
        import subprocess
        import tempfile
        from pathlib import Path
        from nacl.public import PrivateKey
        from family_activity import public_key_file, windows_install
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / 'runtime'; package = runtime / 'family_activity'
            package.mkdir(parents=True); (package / '__main__.py').write_text('')
            python = root / 'pythonw.exe'; python.touch()
            status = root / 'status.exe'; status.touch()
            public = root / 'parent.pub'
            public.write_bytes(public_key_file.encode(PrivateKey.generate().public_key))
            data = root / 'local' / windows_install.FOLDER_NAME
            data.mkdir(parents=True)
            external = root / 'outside-lock'
            external.write_text('unrelated file')
            Path(str(data / 'activity.sqlite3') + '.lock').symlink_to(external)
            calls = []
            def runner(args):
                calls.append(args)
                return subprocess.CompletedProcess(args, 1, '', '')
            with patch.object(windows_install.sys, 'platform', 'win32'), \
                 self.assertRaisesRegex(ValueError, 'symbolic links or reparse points'):
                windows_install.install(public, python, runtime, status, root / 'local',
                                        user='Child', runner=runner)
            self.assertEqual(calls, [])
            self.assertEqual(external.read_text(), 'unrelated file')

    def test_windows_uninstall_ends_verified_running_agent_before_removing_task(self):
        import json
        import subprocess
        import tempfile
        from pathlib import Path
        from family_activity import windows_install, windows_task
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/windows_install.FOLDER_NAME; folder.mkdir()
            user='Child'; python=r'C:\Python\pythonw.exe'; source=r'C:\App'; status=r'C:\App\status.exe'
            database=str(folder/'activity.sqlite3'); public=str(folder/'parent.pub')
            identity=windows_install._identity(user,python,source,status,database,public)
            (folder/windows_install.METADATA_NAME).write_text(json.dumps({'version':1,'identity':identity}))
            xml=windows_task.task_xml(user,python,database,public,status,source)
            calls=[]
            def runner(args):
                calls.append(args)
                if '/XML' in args: return subprocess.CompletedProcess(args,0,xml,'')
                return subprocess.CompletedProcess(args,0 if any(flag in args for flag in ('/Disable','/End','/Delete')) else 1,'','')
            with patch.object(windows_install.sys,'platform','win32'), \
                 patch.object(windows_install,'_agent_running',side_effect=[True,False,False]):
                windows_install.uninstall(Path(tmp),runner=runner)
            self.assertIn('/Disable',calls[1])
            self.assertIn('/End',calls[2])
            self.assertIn('/Delete',calls[3])

    def test_explicit_windows_delete_data_removes_only_known_local_files(self):
        import json
        import subprocess
        import tempfile
        from pathlib import Path
        from family_activity import windows_install
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / windows_install.FOLDER_NAME
            folder.mkdir()
            key = folder / 'parent.pub'; key.write_bytes(b'parent public key')
            database = folder / 'activity.sqlite3'; database.write_bytes(b'encrypted bytes')
            for suffix in ('-wal', '-shm', '-journal', '.lock'):
                Path(str(database) + suffix).write_text('sidecar')
            unrelated = folder / 'notes.txt'; unrelated.write_text('leave this alone')
            identity = windows_install._identity('Child', r'C:\Python\pythonw.exe', r'C:\App',
                                                  r'C:\App\status.exe', str(database), str(key))
            (folder / windows_install.METADATA_NAME).write_text(json.dumps({'version': 1, 'identity': identity}))
            xml = windows_install.windows_task.task_xml('Child', identity['python'], identity['database'],
                                                         identity['public_key'], identity['status'], identity['source'])
            def runner(args):
                if '/XML' in args:
                    return subprocess.CompletedProcess(args, 0, xml, '')
                return subprocess.CompletedProcess(args, 0 if any(flag in args for flag in ('/Disable','/End','/Delete')) else 1, '', '')
            with patch.object(windows_install.sys, 'platform', 'win32'):
                outcome = windows_install.uninstall(Path(tmp), runner=runner, delete_data=True)
            self.assertTrue(outcome['data_deleted'])
            self.assertFalse(key.exists()); self.assertFalse(database.exists())
            self.assertFalse((folder / windows_install.METADATA_NAME).exists())
            for suffix in ('-wal', '-shm', '-journal', '.lock'):
                self.assertFalse(Path(str(database) + suffix).exists())
            self.assertEqual(unrelated.read_text(), 'leave this alone')

    def test_windows_uninstall_preflights_sidecar_symlink_before_stopping_task(self):
        import json
        import tempfile
        from pathlib import Path
        from family_activity import windows_install
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / windows_install.FOLDER_NAME
            folder.mkdir()
            external = root / 'external-data'
            external.write_text('preserve')
            database = folder / 'activity.sqlite3'
            database.write_bytes(b'encrypted')
            sidecar = Path(str(database) + '-wal')
            sidecar.symlink_to(external)
            key = folder / 'parent.pub'
            key.write_bytes(b'public key')
            identity = windows_install._identity('Child', r'C:\Python\pythonw.exe', r'C:\App',
                r'C:\App\status.exe', str(database), str(key))
            metadata = folder / windows_install.METADATA_NAME
            metadata.write_text(json.dumps({'version': 1, 'identity': identity}))
            calls = []
            with patch.object(windows_install.sys, 'platform', 'win32'), \
                 self.assertRaisesRegex(ValueError, 'symbolic link or reparse point'):
                windows_install.uninstall(root, runner=lambda args: calls.append(args), delete_data=True)
            self.assertEqual(calls, [])
            self.assertTrue(metadata.exists())
            self.assertTrue(sidecar.is_symlink())
            self.assertEqual(external.read_text(), 'preserve')

    def test_windows_uninstall_preflights_network_key_symlink_before_stopping_task(self):
        import json
        import tempfile
        from pathlib import Path
        from family_activity import windows_install
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / windows_install.FOLDER_NAME
            folder.mkdir()
            external = root / 'external-key'
            external.write_bytes(b'preserve external file')
            network_key = folder / 'network.key'
            network_key.symlink_to(external)
            database = folder / 'activity.sqlite3'
            database.write_bytes(b'encrypted')
            key = folder / 'parent.pub'
            key.write_bytes(b'public key')
            identity = windows_install._identity('Child', r'C:\Python\pythonw.exe', r'C:\App',
                r'C:\App\status.exe', str(database), str(key))
            metadata = folder / windows_install.METADATA_NAME
            metadata.write_text(json.dumps({'version': 1, 'identity': identity}))
            calls = []
            with patch.object(windows_install.sys, 'platform', 'win32'), \
                 self.assertRaisesRegex(ValueError, 'symbolic links or reparse points'):
                windows_install.uninstall(root, runner=lambda args: calls.append(args), delete_data=True)
            self.assertEqual(calls, [])
            self.assertTrue(metadata.exists())
            self.assertTrue(network_key.is_symlink())
            self.assertEqual(external.read_bytes(), b'preserve external file')

    def test_uninstall_refuses_a_modified_scheduled_task(self):
        import json
        import subprocess
        import tempfile
        from pathlib import Path
        from family_activity import windows_install, windows_task
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/windows_install.FOLDER_NAME; folder.mkdir()
            user='Child'; python=r'C:\Python\pythonw.exe'; source=r'C:\App'; status=r'C:\App\status.exe'
            database=str(folder/'activity.sqlite3'); public=str(folder/'parent.pub')
            identity=windows_install._identity(user, python, source, status, database, public)
            (folder/windows_install.METADATA_NAME).write_text(json.dumps({'version':1,'identity':identity}))
            xml=windows_task.task_xml(user,python,database,public,status,source)
            xml=xml.replace('</Actions>', '<Exec><Command>evil.exe</Command></Exec></Actions>')
            called=[]
            def runner(args):
                called.append(args)
                return subprocess.CompletedProcess(args,0,xml,'')
            with patch.object(windows_install.sys,'platform','win32'), self.assertRaises(ValueError):
                windows_install.uninstall(Path(tmp),runner=runner)
            self.assertEqual(len(called),1)
            self.assertTrue((folder/windows_install.METADATA_NAME).exists())

    def test_uninstall_can_resume_after_task_was_disabled_but_not_removed(self):
        from family_activity import windows_install, windows_task
        identity=windows_install._identity('Child',r'C:\Python\pythonw.exe',r'C:\App',
                                           r'C:\App\status.exe',r'C:\Data\activity.sqlite3',r'C:\Data\parent.pub')
        xml=windows_task.task_xml(identity['user'],identity['python'],identity['database'],
                                  identity['public_key'],identity['status'],identity['source'])
        disabled=xml.replace('<Enabled>true</Enabled>','<Enabled>false</Enabled>')
        self.assertTrue(windows_install._matching_task(disabled,identity))

    def test_failed_task_registration_rolls_back_created_key_and_metadata(self):
        import subprocess
        import tempfile
        from pathlib import Path
        from nacl.public import PrivateKey
        from family_activity import public_key_file, windows_install
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'runtime'; package=source/'family_activity'
            package.mkdir(parents=True); (package/'__main__.py').write_text('')
            python=root/'pythonw.exe'; python.touch(); status=root/'status.exe'; status.touch()
            public=root/'family-public.key'; public.write_bytes(public_key_file.encode(PrivateKey.generate().public_key))
            calls=[]
            def runner(args):
                calls.append(args)
                if '/Query' in args:
                    return subprocess.CompletedProcess(args,1,'','')
                return subprocess.CompletedProcess(args,1,'','registration failed')
            with patch.object(windows_install.sys,'platform','win32'), self.assertRaisesRegex(RuntimeError,'could not register'):
                windows_install.install(public,python,source,status,root/'local',user='Child',runner=runner)
            data=root/'local'/windows_install.FOLDER_NAME
            self.assertFalse((data/'parent.pub').exists())
            self.assertFalse((data/'network.key').exists())
            self.assertFalse((data/windows_install.METADATA_NAME).exists())
            self.assertFalse(any(path.suffix == '.xml' for path in data.iterdir()))
            self.assertEqual(sum('/Query' in call for call in calls),2)

    def test_windows_install_starts_registered_task_and_preserves_uncertain_setup_on_failure(self):
        import subprocess
        import tempfile
        from pathlib import Path
        from nacl.public import PrivateKey
        from family_activity import public_key_file, windows_install
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / 'runtime'; package = runtime / 'family_activity'
            package.mkdir(parents=True); (package / '__main__.py').write_text('')
            python = root / 'pythonw.exe'; python.touch()
            status = root / 'status.exe'; status.touch()
            public = root / 'parent.pub'
            public.write_bytes(public_key_file.encode(PrivateKey.generate().public_key))
            registered = []
            def runner(args):
                if '/Create' in args:
                    registered.append(Path(args[-1]).read_text(encoding='utf-8'))
                    return subprocess.CompletedProcess(args, 0, '', '')
                if '/Run' in args:
                    return subprocess.CompletedProcess(args, 1, '', 'start failed')
                return subprocess.CompletedProcess(args, 1, '', '')
            with patch.object(windows_install.sys, 'platform', 'win32'), \
                 self.assertRaisesRegex(RuntimeError, 'registered, but Windows could not start'):
                windows_install.install(public, python, runtime, status, root / 'local',
                                        user='Child', runner=runner)
            data = root / 'local' / windows_install.FOLDER_NAME
            self.assertTrue((data / windows_install.METADATA_NAME).is_file())
            self.assertTrue((data / 'parent.pub').is_file())
            self.assertTrue(registered)

    def test_windows_install_preserves_task_metadata_if_start_command_times_out(self):
        import subprocess
        import tempfile
        from pathlib import Path
        from nacl.public import PrivateKey
        from family_activity import public_key_file, windows_install
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / 'runtime'; package = runtime / 'family_activity'
            package.mkdir(parents=True); (package / '__main__.py').write_text('')
            python = root / 'pythonw.exe'; python.touch()
            status = root / 'status.exe'; status.touch()
            public = root / 'parent.pub'
            public.write_bytes(public_key_file.encode(PrivateKey.generate().public_key))
            def runner(args):
                if '/Create' in args:
                    return subprocess.CompletedProcess(args, 0, '', '')
                if '/Run' in args:
                    raise subprocess.TimeoutExpired(args, 20)
                return subprocess.CompletedProcess(args, 1, '', '')
            with patch.object(windows_install.sys, 'platform', 'win32'), \
                 self.assertRaises(subprocess.TimeoutExpired):
                windows_install.install(public, python, runtime, status, root / 'local',
                                        user='Child', runner=runner)
            data = root / 'local' / windows_install.FOLDER_NAME
            self.assertTrue((data / windows_install.METADATA_NAME).is_file())
            self.assertTrue((data / 'parent.pub').is_file())

    def test_windows_install_preserves_task_when_ready_session_does_not_appear(self):
        import subprocess
        import tempfile
        from pathlib import Path
        from nacl.public import PrivateKey
        from family_activity import public_key_file, windows_install
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / 'runtime'; package = runtime / 'family_activity'
            package.mkdir(parents=True); (package / '__main__.py').write_text('')
            python = root / 'pythonw.exe'; python.touch()
            status = root / 'status.exe'; status.touch()
            public = root / 'parent.pub'
            public.write_bytes(public_key_file.encode(PrivateKey.generate().public_key))
            registered = []
            def runner(args):
                if '/Create' in args:
                    registered.append(Path(args[-1]).read_text(encoding='utf-8'))
                    return subprocess.CompletedProcess(args, 0, '', '')
                if '/Run' in args:
                    return subprocess.CompletedProcess(args, 0, '', '')
                return subprocess.CompletedProcess(args, 1, '', '')
            with patch.object(windows_install.sys, 'platform', 'win32'), \
                 self.assertRaisesRegex(RuntimeError, 'did not become ready in time'):
                windows_install.install(public, python, runtime, status, root / 'local', user='Child',
                                        runner=runner, readiness_check=lambda *_: False)
            data = root / 'local' / windows_install.FOLDER_NAME
            self.assertTrue((data / windows_install.METADATA_NAME).is_file())
            self.assertTrue((data / 'parent.pub').is_file())
            self.assertTrue(registered)
