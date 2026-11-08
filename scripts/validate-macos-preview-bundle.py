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
                if page.status != 200 or b'Family Activity' not in page_body:
                    raise RuntimeError('the frozen parent dashboard did not serve its local page')
                connection.request('GET', '/api/status')
                status = connection.getresponse()
                status.read()
                if status.status != 403:
                    raise RuntimeError('the frozen parent API did not reject an unauthenticated request')
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

    return 'Frozen setup, agent/share commands, loopback dashboard, and unauthenticated API rejection passed.'


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: validate-macos-preview-bundle.py /path/to/Family Activity Preview.app')
    print(validate(sys.argv[1]))
