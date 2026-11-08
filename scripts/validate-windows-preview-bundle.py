#!/usr/bin/env python3
"""Smoke-check a built Windows preview core and its local parent dashboard.

Runs only the frozen core's CLI and a temporary loopback parent dashboard. It
does not open the setup UI, register a scheduled task, or collect activity.
"""
import http.client
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit


def _run(arguments, timeout=30):
    return subprocess.run(arguments, capture_output=True, text=True, timeout=timeout)


def _validate_windows_heartbeat_ipc(setup):
    if os.name != 'nt':
        return False
    import ctypes
    from ctypes import wintypes
    from family_activity.__main__ import status_heartbeat

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateEventW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.CreateEventW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL

    token = secrets.token_hex(16)
    ready_name = 'Local\\FamilyActivity-StatusTestReady-' + token
    heartbeat_name = 'Local\\FamilyActivity-StatusTestHeartbeat-' + token
    ready = kernel.CreateEventW(None, True, False, ready_name)
    if not ready:
        raise RuntimeError('the Windows tray heartbeat self-test could not create its readiness event')
    process = None
    try:
        environment = os.environ.copy()
        environment['FAMILY_ACTIVITY_READY_EVENT'] = ready_name
        environment['FAMILY_ACTIVITY_HEARTBEAT_EVENT'] = heartbeat_name
        process = subprocess.Popen(
            [str(setup), '--self-test-status-ipc'], env=environment,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000),
        )
        if kernel.WaitForSingleObject(ready, 10000) != 0 or process.poll() is not None:
            raise RuntimeError('the Windows tray heartbeat self-test did not become ready')
        process._family_activity_heartbeat_event = heartbeat_name
        status_heartbeat(process)
        try:
            return_code = process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            raise RuntimeError('the Windows tray heartbeat self-test did not finish') from None
        if return_code:
            raise RuntimeError('the Windows tray heartbeat self-test rejected the event')
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        kernel.CloseHandle(ready)
    return True


def _validate_frozen_report_timezone(connection, port, token, temporary_root):
    """Open a saved IANA schedule and report inside the frozen parent process."""
    from family_activity.encrypted_agent_store import EncryptedAgentStore
    from family_activity.public_key_file import decode

    origin = f'http://127.0.0.1:{port}'
    cookie = None

    def request(method, path, body=None, content_type='application/json'):
        headers = {}
        if method == 'POST':
            headers.update({'Origin': origin, 'Content-Type': content_type})
        if cookie:
            headers['Cookie'] = cookie
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, response.getheaders(), response.read()

    def post_json(path, value):
        return request('POST', path, json.dumps(value).encode('utf-8'))

    status, headers, _ = post_json('/api/login', {'token': token})
    if status != 200:
        raise RuntimeError('the packaged parent could not start an authenticated timezone check')
    session_cookie = next((value for name, value in headers if name.lower() == 'set-cookie'), None)
    if not session_cookie:
        raise RuntimeError('the packaged parent did not create its local session cookie')
    cookie = session_cookie.split(';', 1)[0]

    status, _, _ = post_json('/api/create', {'passphrase': '638204', 'confirm': '638204'})
    if status != 200:
        raise RuntimeError('the packaged parent could not create a temporary test key')
    status, _, backup = request('GET', '/api/backup')
    if status != 200 or not backup:
        raise RuntimeError('the packaged parent could not export a temporary key backup')
    status, _, _ = post_json('/api/confirm-key-backup', {'confirmed': True})
    if status != 200:
        raise RuntimeError('the packaged parent could not confirm its temporary key backup')
    status, _, public = request('GET', '/api/public')
    if status != 200:
        raise RuntimeError('the packaged parent could not export its temporary public key')

    activity = Path(temporary_root) / 'timezone-report.sqlite3'
    writer = EncryptedAgentStore(activity, decode(public), 30)
    try:
        writer.event('start')
        writer.event('stop')
    finally:
        writer.close()
    status, _, _ = request('POST', '/api/import', activity.read_bytes(), 'application/octet-stream')
    if status != 200:
        raise RuntimeError('the packaged parent could not import a temporary encrypted report')
    schedule = {'timezone': 'Europe/Vienna', 'days': [0, 1, 2, 3, 4], 'start': '08:30', 'end': '15:00'}
    status, _, _ = post_json('/api/schedule', schedule)
    if status != 200:
        raise RuntimeError('the packaged parent could not save an IANA school schedule')
    status, _, report = request('GET', '/api/report')
    if status != 200:
        raise RuntimeError('the packaged parent could not open a report with an IANA schedule')
    data = json.loads(report)
    if (data.get('report_timezone') != 'Europe/Vienna' or
            not data.get('traffic_contexts', {}).get('schedule_configured')):
        raise RuntimeError('the packaged parent did not apply the IANA report time zone')
    return 'frozen IANA schedule/report check passed (Europe/Vienna)'


def validate(package_path):
    package = Path(package_path).expanduser().resolve(strict=True)
    setup = package / 'FamilyActivitySetup.exe'
    core = package / 'FamilyActivityCore' / 'FamilyActivityCore.exe'
    if not setup.is_file() or not core.is_file():
        raise RuntimeError('the preview is missing its setup executable or frozen core')

    for command in ('agent', 'share', 'export-report'):
        result = _run([str(core), command, '--help'])
        if result.returncode:
            raise RuntimeError(f'the frozen {command} command failed: {result.stderr.strip()}')

    with tempfile.TemporaryDirectory(prefix='family-activity-windows-smoke-') as temporary:
        root = Path(temporary)
        data = root / 'parent-data'
        url_file = root / 'session-url.txt'
        stop_file = root / 'stop-parent.txt'
        process = subprocess.Popen(
            [str(core), 'parent', '--no-browser', '--data-dir', str(data),
             '--url-file', str(url_file), '--stop-file', str(stop_file)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        try:
            deadline = time.monotonic() + 15
            session_url = ''
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError('the frozen parent process exited during startup')
                try:
                    session_url = url_file.read_text(encoding='utf-8').strip()
                except (FileNotFoundError, PermissionError):
                    pass
                if session_url:
                    break
                time.sleep(0.05)
            if not session_url:
                raise RuntimeError('the frozen parent process did not publish its local session URL')

            parsed = urlsplit(session_url)
            if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.port is None:
                raise RuntimeError('the frozen parent URL is not bound to loopback')

            connection = http.client.HTTPConnection('127.0.0.1', parsed.port, timeout=5)
            try:
                connection.request('GET', '/')
                page = connection.getresponse()
                body = page.read()
                if page.status != 200 or b'Family Activity' not in body:
                    raise RuntimeError('the frozen parent dashboard did not serve its local page')
                connection.request('GET', '/api/status')
                status = connection.getresponse()
                status.read()
                if status.status != 403:
                    raise RuntimeError('the frozen parent API did not reject an unauthenticated request')
                timezone_check = _validate_frozen_report_timezone(
                    connection, parsed.port, parsed.fragment, root)
            finally:
                connection.close()
        finally:
            try:
                stop_file.write_text('stop', encoding='utf-8')
            except OSError:
                if process.poll() is None:
                    process.terminate()
            try:
                return_code = process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                raise RuntimeError('the frozen parent process did not stop cleanly') from None
            if return_code != 0:
                raise RuntimeError('the frozen parent process did not shut down cleanly')

    heartbeat = 'Windows named-event heartbeat passed.' if _validate_windows_heartbeat_ipc(setup) else 'Windows named-event check skipped on this host.'
    return f'Frozen agent/share commands, loopback dashboard, unauthenticated API rejection, {timezone_check}, and {heartbeat}'


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: validate-windows-preview-bundle.py /path/to/FamilyActivityPreview')
    print(validate(sys.argv[1]))
