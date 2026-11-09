#!/usr/bin/env python3
"""Smoke-check the frozen commands and local parent UI in a built Mac app.

This starts only the loopback parent dashboard with an empty temporary data
directory. It does not open the GUI, install a LaunchAgent, or collect activity.
"""
import http.client
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit


def _run(arguments, timeout=30):
    return subprocess.run(arguments, capture_output=True, text=True, timeout=timeout)


def _validate_frozen_file_return(core, connection, port, token, temporary_root):
    """Round-trip a synthetic encrypted report through the packaged exporter."""
    import json
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
        raise RuntimeError('the packaged parent could not start a temporary export check')
    session_cookie = next((value for name, value in headers if name.lower() == 'set-cookie'), None)
    if not session_cookie:
        raise RuntimeError('the packaged parent did not create its temporary session cookie')
    cookie = session_cookie.split(';', 1)[0]
    status, _, _ = post_json('/api/create', {'passphrase': '638204', 'confirm': '638204'})
    if status != 200:
        raise RuntimeError('the packaged parent could not create a temporary test key')
    status, _, backup = request('GET', '/api/backup')
    if status != 200 or not backup:
        raise RuntimeError('the packaged parent could not create a temporary key backup')
    status, _, _ = post_json('/api/confirm-key-backup', {'confirmed': True})
    if status != 200:
        raise RuntimeError('the packaged parent could not confirm its temporary backup')
    status, _, public = request('GET', '/api/public')
    if status != 200:
        raise RuntimeError('the packaged parent could not provide a temporary public key')

    root = Path(temporary_root)
    source = root / 'synthetic-child.sqlite3'
    destination = root / 'synthetic-report.sqlite3'
    writer = EncryptedAgentStore(source, decode(public), 30)
    try:
        writer.event('start')
        writer.event('foreground', application=['PREVIEW_FILE_RETURN_SAMPLE', 'org.example.preview'])
        writer.event('foreground', application=['PREVIEW_FILE_RETURN_SAMPLE', 'org.example.preview'])
        writer.event('stop')
    finally:
        writer.close()
    result = _run([str(core), 'export-report', '--db', str(source), '--output', str(destination)])
    if result.returncode or not destination.is_file():
        raise RuntimeError('the frozen report exporter failed: ' + result.stderr.strip())
    report_bytes = destination.read_bytes()
    if b'PREVIEW_FILE_RETURN_SAMPLE' in report_bytes:
        raise RuntimeError('the exported report contains a synthetic plaintext app name')
    status, _, _ = request('POST', '/api/import', report_bytes, 'application/octet-stream')
    if status != 200:
        raise RuntimeError('the packaged parent could not open the exported report file')
    status, _, report = request('GET', '/api/report')
    if status != 200 or b'PREVIEW_FILE_RETURN_SAMPLE' not in report:
        raise RuntimeError('the packaged parent did not decrypt the exported synthetic report')
    return 'frozen encrypted file export/import round-trip passed'


def validate(app_path):
    app = Path(app_path).expanduser().resolve(strict=True)
    setup = app / 'Contents' / 'MacOS' / 'FamilyActivitySetup'
    core = app / 'Contents' / 'Resources' / 'runtime' / 'FamilyActivityCore'
    if not setup.is_file() or not core.is_file():
        raise RuntimeError('the app is missing its setup executable or frozen runtime')

    checked = _run([str(setup), '--check-bundle'])
    if checked.returncode:
        raise RuntimeError('the bundled setup check failed: ' + checked.stderr.strip())
    for command in ('agent', 'share', 'export-report'):
        result = _run([str(core), command, '--help'])
        if result.returncode:
            raise RuntimeError(f'the frozen {command} command failed: {result.stderr.strip()}')

    with tempfile.TemporaryDirectory(prefix='family-activity-bundle-smoke-') as data_dir:
        process = subprocess.Popen(
            [str(core), 'parent', '--no-browser', '--data-dir', data_dir],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
        )
        try:
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            lines = []
            pending = bytearray()
            deadline = time.monotonic() + 15
            while len(lines) < 2 and time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError('the frozen parent process exited during startup')
                if selector.select(timeout=min(0.25, max(0, deadline - time.monotonic()))):
                    byte = os.read(process.stdout.fileno(), 1)
                    if not byte:
                        raise RuntimeError('the frozen parent process closed its startup output')
                    if byte == b'\n':
                        lines.append(pending.decode('utf-8').strip())
                        pending.clear()
                    else:
                        pending.extend(byte)
            selector.close()
            if len(lines) != 2 or '127.0.0.1' not in lines[0]:
                raise RuntimeError('the frozen parent process did not report its loopback URL')
            parsed = urlsplit(lines[1])
            if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.port is None:
                raise RuntimeError('the frozen parent URL is not bound to loopback')

            connection = http.client.HTTPConnection('127.0.0.1', parsed.port, timeout=5)
            try:
                connection.request('GET', '/')
                page = connection.getresponse()
                page_body = page.read()
                if page.status != 200 or b'Ruffster' not in page_body:
                    raise RuntimeError('the frozen parent dashboard did not serve its local page')
                connection.request('GET', '/api/status')
                status = connection.getresponse()
                status.read()
                if status.status != 403:
                    raise RuntimeError('the frozen parent API did not reject an unauthenticated request')
                file_return = _validate_frozen_file_return(
                    core, connection, parsed.port, parsed.fragment, data_dir)
            finally:
                connection.close()
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                return_code = process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                raise RuntimeError('the frozen parent process did not stop cleanly') from None
            if process.stdout:
                process.stdout.close()
            if return_code != 0:
                raise RuntimeError('the frozen parent process did not shut down cleanly')

    return f'Frozen setup, agent/share commands, loopback dashboard, unauthenticated API rejection, and {file_return}.'


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: validate-macos-preview-bundle.py /path/to/Ruffster.app')
    print(validate(sys.argv[1]))
