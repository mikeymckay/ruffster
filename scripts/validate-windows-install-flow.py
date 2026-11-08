"""Exercise a synthetic Family Activity agent through the real Windows task lifecycle.

Run from a logged-in Windows session against the packaged preview. The task
uses a renamed copy of the companion that emits one fictional foreground app;
network and system-setting collection are disabled. No real user activity is
sampled. Setup registers and starts the task, then verifies a live encrypted
session before the validator kills the synthetic agent once to check Task
Scheduler restart and gap reconstruction. It then uses the real uninstaller
and removes its temporary profile.
"""
import json
import os
from pathlib import Path
import sqlite3
import shutil
import subprocess
import sys
import tempfile
import time

import psutil
from nacl.public import PrivateKey

from family_activity import encrypted_view, public_key_file, windows_install


TASK_EXE = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'schtasks.exe'
SYNTHETIC_APP = ('Synthetic Study App', 'org.example.synthetic-study')


def _run_task(*args):
    return subprocess.run([str(TASK_EXE), *args], capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=25, shell=False)


def _agent_pids(core, database):
    expected_exe = str(Path(core).resolve()).casefold()
    expected_db = str(Path(database).resolve()).casefold()
    found = []
    for process in psutil.process_iter(attrs=('exe', 'cmdline')):
        try:
            info = process.info
            executable = info.get('exe')
            command = info.get('cmdline') or []
            if (executable and str(Path(executable).resolve()).casefold() == expected_exe and
                    expected_db in ' '.join(command).casefold() and ' agent ' in (' ' + ' '.join(command).casefold() + ' ')):
                found.append(process.pid)
        except (OSError, psutil.Error):
            continue
    return found


def _report(database, private_key):
    projection, incomplete = encrypted_view.open_projection(database, private_key)
    try:
        return {
            'incomplete': incomplete,
            'samples': projection.execute('SELECT app_name, bundle_id FROM foreground_samples ORDER BY id').fetchall(),
            'sessions': projection.execute('SELECT started_at, heartbeat_at, stopped_at FROM sessions ORDER BY id').fetchall(),
            'gaps': projection.execute('SELECT from_at, to_at FROM gaps ORDER BY id').fetchall(),
            'networks': projection.execute('SELECT count(*) FROM network_samples').fetchone()[0],
            'settings': projection.execute('SELECT count(*) FROM network_settings').fetchone()[0],
        }
    finally:
        projection.close()


def _wait_for(database, private_key, core, *, timeout, minimum_samples, minimum_sessions,
              require_gap=False, old_pid=None):
    deadline = time.monotonic() + timeout
    last_report = None
    last_pids = []
    while time.monotonic() < deadline:
        last_pids = _agent_pids(core, database)
        if database.exists():
            try:
                last_report = _report(database, private_key)
            except (OSError, ValueError, sqlite3.Error):
                last_report = None
        if (last_report is not None and len(last_report['samples']) >= minimum_samples and
                len(last_report['sessions']) >= minimum_sessions and
                (not require_gap or bool(last_report['gaps'])) and
                (old_pid is None or any(pid != old_pid for pid in last_pids))):
            return last_report, last_pids
        time.sleep(0.5)
    raise RuntimeError(f'agent lifecycle timed out (pids={last_pids}, report={last_report})')


def validate(package):
    if sys.platform != 'win32':
        raise SystemExit('Run this validation on Windows.')
    package = Path(package).resolve()
    core = package / 'FamilyActivityCore' / 'FamilyActivityCore.exe'
    companion = package / 'FamilyActivitySetup.exe'
    if not core.is_file() or not companion.is_file():
        raise ValueError('the packaged Windows core or companion is missing')

    root = Path(tempfile.mkdtemp(prefix='family-activity-task-check-'))
    profile = root / 'profile'
    data_root = profile / windows_install.FOLDER_NAME
    database = data_root / 'activity.sqlite3'
    metadata = data_root / windows_install.METADATA_NAME
    try:
        synthetic_helper = root / 'FamilyActivitySyntheticForeground.exe'
        shutil.copy2(companion, synthetic_helper)
        fixture = subprocess.run([str(synthetic_helper)], capture_output=True, text=True,
                                 encoding='utf-8', errors='replace', timeout=10, shell=False)
        if fixture.returncode != 0 or json.loads(fixture.stdout) != {
                'name': SYNTHETIC_APP[0], 'bundle_id': SYNTHETIC_APP[1]}:
            raise RuntimeError('packaged synthetic foreground helper did not return its fictional app identity')

        private_key = PrivateKey.generate()
        public_key = root / 'parent.pub'
        public_key.write_bytes(public_key_file.encode(private_key.public_key))
        username = os.environ.get('USERNAME')
        domain = os.environ.get('USERDOMAIN')
        user = f'{domain}\\{username}' if domain and username else username
        if not user:
            raise RuntimeError('could not determine the current Windows account')

        result = windows_install.install(
            public_key, core, package, companion, profile, user=user,
            packaged=True, foreground_helper=synthetic_helper,
            monitor_network=False, inspect_network_settings=False)
        data_root = Path(result['data_directory'])
        database = data_root / 'activity.sqlite3'
        metadata = data_root / windows_install.METADATA_NAME
        first_report, pids = _wait_for(database, private_key, core, timeout=60,
                                       minimum_samples=2, minimum_sessions=1)
        if not pids:
            raise RuntimeError('the encrypted synthetic agent sampled but its process could not be identified')
        if any(sample != SYNTHETIC_APP for sample in first_report['samples']):
            raise RuntimeError('the initial report contains unexpected foreground activity')
        if first_report['networks'] or first_report['settings']:
            raise RuntimeError('the synthetic lifecycle check unexpectedly collected network data')
        if SYNTHETIC_APP[0].encode() in database.read_bytes() or SYNTHETIC_APP[1].encode() in database.read_bytes():
            raise RuntimeError('synthetic foreground plaintext appeared in the encrypted database')

        first_pid = pids[0]
        process = psutil.Process(first_pid)
        process.kill()
        process.wait(timeout=10)
        restarted, restarted_pids = _wait_for(
            database, private_key, core, timeout=140, minimum_samples=3,
            minimum_sessions=2, require_gap=True, old_pid=first_pid)
        if any(sample != SYNTHETIC_APP for sample in restarted['samples']):
            raise RuntimeError('the restarted report contains unexpected foreground activity')
        if restarted['networks'] or restarted['settings']:
            raise RuntimeError('the restarted synthetic check unexpectedly collected network data')

        removed = windows_install.uninstall(profile)
        if removed['data_deleted'] or not database.is_file() or not (data_root / 'parent.pub').is_file():
            raise RuntimeError('normal removal did not retain the synthetic encrypted report and public key')
        if _run_task('/Query', '/TN', windows_install.TASK_NAME).returncode == 0:
            raise RuntimeError('normal removal left the disposable scheduled task registered')
        if windows_install._agent_running(database):
            raise RuntimeError('normal removal left the disposable agent running')
        final = _report(database, private_key)
        if len(final['sessions']) != 2 or final['sessions'][-1][2] is None:
            raise RuntimeError('removal did not close the final synthetic session')
        return ('Real Windows Task Scheduler install/start/restart/uninstall passed: '
                'synthetic foreground samples were encrypted, network collection stayed off, '
                'a forced exit produced a second session and gap, and removal stopped the task '
                'while retaining the report by default.')
    finally:
        if metadata.exists():
            try:
                windows_install.uninstall(profile, delete_data=True)
            except (OSError, RuntimeError, ValueError) as error:
                raise RuntimeError(f'could not safely clean up the disposable Windows task; preserve {root}: {error}') from error
        if metadata.exists() or windows_install._agent_running(database):
            raise RuntimeError(f'disposable Windows task still has state; preserve temporary data at {root}')
        shutil.rmtree(root, ignore_errors=False)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: validate-windows-install-flow.py <packaged-preview-folder>')
    print(validate(sys.argv[1]))
