import sys
import unittest
from unittest.mock import patch
from family_activity.__main__ import start_status, stop_status

class StatusTests(unittest.TestCase):
    def test_successful_status_is_stopped(self):
        import subprocess
        real = subprocess.Popen
        with patch('family_activity.__main__.subprocess.Popen', side_effect=lambda *a, **kw: real([sys.executable, '-u', '-c', 'import time; print("READY"); time.sleep(30)'], **kw)) as popen:
            child = start_status('ignored', interval=7)
            self.assertEqual(popen.call_args.kwargs['stdin'], subprocess.PIPE)
            self.assertEqual(popen.call_args.kwargs['env']['FAMILY_ACTIVITY_SAMPLE_INTERVAL'], '7')
            self.assertIsNone(child.poll())
            stop_status(child)
            self.assertIsNotNone(child.poll())

    def test_status_heartbeat_reports_completed_sample(self):
        import io
        from family_activity.__main__ import status_heartbeat
        class Process:
            stdin = io.BytesIO()
            def poll(self): return None
        process = Process()
        status_heartbeat(process)
        self.assertEqual(process.stdin.getvalue(), b'HEARTBEAT\n')

    def test_status_heartbeat_fails_closed_when_indicator_stops(self):
        from family_activity.__main__ import status_heartbeat
        class Process:
            stdin = None
            def poll(self): return 0
        with self.assertRaisesRegex(RuntimeError, 'Status indicator stopped'):
            status_heartbeat(Process())

    def test_failed_status_is_rejected(self):
        import subprocess
        real = subprocess.Popen
        with patch('family_activity.__main__.subprocess.Popen', side_effect=lambda *a, **kw: real([sys.executable, '-u', '-c', 'print("ERROR")'], **kw)):
            with self.assertRaises(RuntimeError):
                start_status('ignored')

    def test_windows_gui_status_uses_private_readiness_event(self):
        import ctypes
        import subprocess
        class Call:
            def __init__(self, result): self.result, self.calls = result, []
            def __call__(self, *args): self.calls.append(args); return self.result
        class Kernel:
            def __init__(self):
                self.CreateEventW = Call(41)
                self.WaitForSingleObject = Call(0)
                self.CloseHandle = Call(1)
        class Process:
            stdout = None
            def poll(self): return None
            def terminate(self): pass
            def wait(self, **kwargs): pass
        kernel = Kernel(); process = Process()
        with patch('family_activity.__main__.sys.platform','win32'), \
             patch.object(ctypes,'WinDLL',create=True,return_value=kernel), \
             patch('family_activity.__main__.secrets.token_hex',return_value='a'*32), \
             patch('family_activity.__main__.subprocess.Popen',return_value=process) as popen:
            self.assertIs(start_status('status.exe','activity.sqlite3',retention_days=90,interval=7.5),process)
        event_name = kernel.CreateEventW.calls[0][-1]
        self.assertTrue(event_name.startswith('Local\\FamilyActivity-Ready-'))
        self.assertEqual(kernel.WaitForSingleObject.calls[0],(41,10000))
        self.assertEqual(kernel.CloseHandle.calls,[(41,)])
        args, = popen.call_args.args
        self.assertEqual(args,['status.exe'])
        self.assertTrue(popen.call_args.kwargs['env']['FAMILY_ACTIVITY_READY_EVENT'] == event_name)
        self.assertEqual(popen.call_args.kwargs['env']['FAMILY_ACTIVITY_RETENTION_DAYS'],'90')
        self.assertEqual(popen.call_args.kwargs['env']['FAMILY_ACTIVITY_SAMPLE_INTERVAL'],'7.5')
        heartbeat_name = popen.call_args.kwargs['env']['FAMILY_ACTIVITY_HEARTBEAT_EVENT']
        self.assertTrue(heartbeat_name.startswith('Local\\FamilyActivity-Heartbeat-'))
        self.assertEqual(process._family_activity_heartbeat_event, heartbeat_name)
        self.assertEqual(popen.call_args.kwargs['stdout'],subprocess.DEVNULL)

    def test_windows_status_heartbeat_signals_the_companion_event(self):
        import ctypes
        from family_activity.__main__ import status_heartbeat
        class Call:
            def __init__(self, result): self.result, self.calls = result, []
            def __call__(self, *args): self.calls.append(args); return self.result
        class Kernel:
            def __init__(self):
                self.OpenEventW = Call(42)
                self.SetEvent = Call(1)
                self.CloseHandle = Call(1)
        class Process:
            _family_activity_heartbeat_event = 'Local\\FamilyActivity-Heartbeat-test'
            def poll(self): return None
        kernel = Kernel()
        with patch('family_activity.__main__.sys.platform', 'win32'), \
             patch.object(ctypes, 'WinDLL', create=True, return_value=kernel):
            status_heartbeat(Process())
        self.assertEqual(kernel.OpenEventW.calls, [(0x0002, False, Process._family_activity_heartbeat_event)])
        self.assertEqual(kernel.SetEvent.calls, [(42,)])
        self.assertEqual(kernel.CloseHandle.calls, [(42,)])

    def test_windows_status_heartbeat_fails_closed_when_companion_event_is_gone(self):
        import ctypes
        from family_activity.__main__ import status_heartbeat
        class Call:
            def __init__(self, result): self.result = result
            def __call__(self, *args): return self.result
        class Kernel:
            OpenEventW = Call(0)
            SetEvent = Call(1)
            CloseHandle = Call(1)
        class Process:
            _family_activity_heartbeat_event = 'Local\\FamilyActivity-Heartbeat-missing'
            def poll(self): return None
        with patch('family_activity.__main__.sys.platform', 'win32'), \
             patch.object(ctypes, 'WinDLL', create=True, return_value=Kernel()), \
             self.assertRaisesRegex(RuntimeError, 'Status indicator stopped'):
            status_heartbeat(Process())

    def test_agent_signals_windows_status_only_after_complete_sample_storage(self):
        from pathlib import Path
        source = (Path(__file__).parents[1] / 'family_activity/__main__.py').read_text(encoding='utf-8')
        loop = source[source.index('while not done.wait'):source.index('finally:\n        try:\n            try:\n                sealed.event("stop")')]
        self.assertIn("if sys.platform in ('darwin', 'win32'):\n                status_heartbeat(status)", loop)
        self.assertLess(loop.index('sealed.event("tick"'), loop.index('sealed.prune()'))
        self.assertLess(loop.index('sealed.prune()'), loop.index('status_heartbeat(status)'))

    def test_windows_gui_status_timeout_stops_helper(self):
        import ctypes
        class Call:
            def __init__(self, result): self.result = result
            def __call__(self, *args): return self.result
        class Kernel:
            CreateEventW = Call(41)
            WaitForSingleObject = Call(258)
            CloseHandle = Call(1)
        class Process:
            stdout = None
            stopped = False
            def poll(self): return None if not self.stopped else 1
            def terminate(self): self.stopped = True
            def wait(self, **kwargs): pass
        process=Process()
        with patch('family_activity.__main__.sys.platform','win32'), \
             patch.object(ctypes,'WinDLL',create=True,return_value=Kernel()), \
             patch('family_activity.__main__.subprocess.Popen',return_value=process), \
             self.assertRaisesRegex(RuntimeError,'Status indicator could not start'):
            start_status('status.exe')
        self.assertTrue(process.stopped)
