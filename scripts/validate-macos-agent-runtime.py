"""Exercise the live encrypted agent and status helper using synthetic input.

Run this only in a logged-in macOS GUI session with the project dependencies
installed. It creates a temporary database and local helper that returns a
fictional application name, then exercises the real installer with a uniquely
named, synthetic-only LaunchAgent in a temporary home directory. It never
inspects real foreground applications, network traffic, DNS, or browser activity.
"""
import os
from pathlib import Path
import plistlib
import re
import select
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime

from nacl.public import PrivateKey

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from family_activity import encrypted_view, macos_install, public_key_file


class _AgentCleanupError(RuntimeError):
    pass


def _projection(path, private_key):
    db, _ = encrypted_view.open_projection(path, private_key)
    try:
        return {
            'samples': db.execute('SELECT app_name, bundle_id FROM foreground_samples').fetchall(),
            'gaps': db.execute('SELECT from_at, to_at FROM gaps').fetchall(),
            'sessions': db.execute('SELECT started_at, heartbeat_at, stopped_at FROM sessions').fetchall(),
        }
    finally:
        db.close()


def _launchctl(*arguments):
    return subprocess.run(['/bin/launchctl', *arguments], capture_output=True,
                          text=True, timeout=20)


def _service_pid(domain, label):
    result = _launchctl('print', f'{domain}/{label}')
    if result.returncode != 0 or 'state = running' not in result.stdout:
        return None
    match = re.search(r'^\s*pid = (\d+)$', result.stdout, re.MULTILINE)
    return int(match.group(1)) if match else None


def _service_present(domain, label):
    """Return whether launchd still has the job registered, even if it stopped."""
    return _launchctl('print', f'{domain}/{label}').returncode == 0


def _wait_for_samples(database, private_key, minimum, timeout):
    deadline = time.monotonic() + timeout
    report = {'samples': [], 'gaps': [], 'sessions': []}
    while time.monotonic() < deadline:
        if database.exists():
            report = _projection(database, private_key)
            if len(report['samples']) >= minimum:
                return report
        time.sleep(0.2)
    return report


def _validate_launchd(root, folder, foreground, status):
    """Run the synthetic agent through the real installer and launchd KeepAlive."""
    uid = os.getuid()
    domain = f'gui/{uid}'
    label = 'org.familyactivity.validation.' + uuid.uuid4().hex
    home = folder / 'launchd-home'
    home.mkdir(mode=0o700)
    public_path = folder / 'launchd-parent.pub'
    bundle_contents = folder / 'Synthetic Family Activity.app' / 'Contents'
    runtime = bundle_contents / 'Resources' / 'runtime'
    runtime.mkdir(parents=True)
    shutil.copytree(root / 'family_activity', runtime / 'family_activity',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (bundle_contents / 'Info.plist').write_bytes(plistlib.dumps(
        {'CFBundleIdentifier': 'org.familyactivity.validation.synthetic'}))
    private_key = PrivateKey.generate()
    public_path.write_bytes(public_key_file.encode(private_key.public_key))
    runner = lambda arguments: subprocess.run(arguments, capture_output=True, text=True, timeout=20)
    installed = False
    plist_path = home / 'Library' / 'LaunchAgents' / f'{label}.plist'
    try:
        installed_paths = macos_install.install(
            public_path, sys.executable, runtime, foreground, status, home, uid,
            label=label, runner=runner, retention_days=30,
            collect_network=False, collect_network_settings=False)
        installed = True
        database = Path(installed_paths['data_directory']) / 'activity.sqlite3'
        plist_path = Path(installed_paths['plist'])
        installed_definition = plistlib.loads(plist_path.read_bytes())
        arguments = installed_definition['ProgramArguments']
        if installed_definition.get('AssociatedBundleIdentifiers') != [
                'org.familyactivity.validation.synthetic']:
            raise RuntimeError('launch agent did not identify its synthetic host app bundle')
        if '--experimental-network' in arguments or '--experimental-network-settings' in arguments:
            raise RuntimeError('synthetic-only installer enabled network observations')
        first = _wait_for_samples(database, private_key, 2, 45)
        if len(first['samples']) < 2 or len(first['sessions']) != 1:
            state = _launchctl('print', f'{domain}/{label}')
            raise RuntimeError(
                'the real installer-managed launchd agent did not record its initial synthetic samples '
                f'(samples={len(first["samples"])}, sessions={len(first["sessions"])}; '
                f'launchd={state.stdout.strip()} {state.stderr.strip()})')
        first_pid = _service_pid(domain, label)
        if first_pid is None:
            raise RuntimeError('launchd did not report the synthetic agent as running')
        update = macos_install.restart_after_update(
            home, uid, sys.executable, runtime, foreground, status,
            label=label, runner=runner)
        if update['pid'] == first_pid or update['previous_pid'] != first_pid:
            raise RuntimeError('the update action did not replace the managed agent process')
        report = _wait_for_samples(database, private_key, 4, 45)
        if len(report['samples']) < 4 or len(report['sessions']) < 2:
            raise RuntimeError('the updated agent did not resume encrypted synthetic sampling')

        result = _launchctl('kill', 'SIGKILL', f'{domain}/{label}')
        if result.returncode:
            raise RuntimeError('could not terminate the synthetic launchd agent: ' + result.stderr.strip())

        deadline = time.monotonic() + 40
        restarted_pid = None
        while time.monotonic() < deadline:
            pid = _service_pid(domain, label)
            if pid is not None and pid != update['pid']:
                restarted_pid = pid
                if database.exists():
                    report = _projection(database, private_key)
                    if len(report['sessions']) >= 3 and len(report['samples']) >= 6 and report['gaps']:
                        break
            time.sleep(0.25)
        if restarted_pid is None or len(report['sessions']) < 3 or not report['gaps']:
            raise RuntimeError('launchd did not restart the real agent into a new encrypted session with an observed gap')
        if any(name != 'Synthetic Study App' or bundle != 'org.example.synthetic-study'
               for name, bundle in report['samples']):
            raise RuntimeError('the restarted agent report contained unexpected foreground data')
        if b'Synthetic Study App' in database.read_bytes() or b'org.example.synthetic-study' in database.read_bytes():
            raise RuntimeError('synthetic foreground plaintext was present in the launchd database')

        removed = macos_install.uninstall(home, uid, label=label, runner=runner)
        installed = False
        if removed['data_deleted'] or not database.exists():
            raise RuntimeError('installer removal did not retain the encrypted synthetic data by default')
        if _service_pid(domain, label) is not None:
            raise RuntimeError('installer removal left the disposable agent registered')
        final = _projection(database, private_key)
        if len(final['sessions']) != 3 or final['sessions'][-1][2] is None:
            raise RuntimeError('installer removal did not close the restarted agent session')
        process = subprocess.run(['/bin/ps', '-p', str(restarted_pid)], capture_output=True, text=True)
        if process.returncode == 0:
            raise RuntimeError('installer removal left the synthetic agent process running')
        shutil.rmtree(installed_paths['data_directory'])
        if Path(installed_paths['data_directory']).exists():
            raise RuntimeError('temporary encrypted data remained after validation cleanup')
        interval = (datetime.fromisoformat(report['gaps'][0][1]) -
                    datetime.fromisoformat(report['gaps'][0][0])).total_seconds()
        return (f'real installer started the synthetic agent; the update action replaced its PID and '
                f'resumed encrypted sampling, then launchd restarted it after SIGKILL and recorded a '
                f'{interval:.1f}-second gap. Uninstall stopped the job and retained the encrypted report; '
                'the validation harness then removed its temporary home.')
    finally:
        if installed:
            try:
                macos_install.uninstall(home, uid, label=label, runner=runner, delete_data=True)
            except (OSError, RuntimeError, ValueError):
                pass
        if _service_present(domain, label):
            bootout = _launchctl('bootout', domain, str(plist_path))
            if bootout.returncode and _service_present(domain, label):
                _launchctl('bootout', f'{domain}/{label}')
            if _service_present(domain, label):
                raise _AgentCleanupError('validation cleanup could not stop the temporary LaunchAgent')


def validate():
    if sys.platform != 'darwin':
        raise SystemExit('Run this validation on macOS.')
    root = PROJECT_ROOT
    with tempfile.TemporaryDirectory(prefix='family-activity-agent-check-') as temporary:
        folder = Path(temporary)
        os.chmod(folder, 0o700)
        status = folder / 'status'
        foreground = folder / 'synthetic-foreground'
        database = folder / 'activity.sqlite3'
        public_path = folder / 'parent.pub'
        private_key = PrivateKey.generate()
        public_path.write_bytes(bytes(private_key.public_key))
        foreground.write_text(
            '#!/bin/sh\nprintf \'%s\\n\' \'{"name":"Synthetic Study App","bundle_id":"org.example.synthetic-study"}\'\n',
            encoding='utf-8')
        foreground.chmod(0o700)
        subprocess.run(['/usr/bin/swiftc', str(root / 'native/macos/status.swift'), '-o', str(status)],
                       check=True, timeout=60)

        command = [sys.executable, '-m', 'family_activity', 'agent',
                   '--db', str(database), '--interval', '2',
                   '--experimental-public-key', str(public_path),
                   '--experimental-foreground-helper', str(foreground),
                   '--experimental-status-helper', str(status)]
        environment = os.environ.copy()
        environment['PYTHONPATH'] = str(root) + os.pathsep + environment.get('PYTHONPATH', '')
        process = subprocess.Popen(command, cwd=root, env=environment,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            startup_lines = []
            startup_deadline = time.monotonic() + 15
            while time.monotonic() < startup_deadline:
                ready, _, _ = select.select([process.stdout], [], [], startup_deadline - time.monotonic())
                if not ready:
                    break
                line = process.stdout.readline()
                if not line:
                    break
                startup_lines.append(line.strip())
                if line.startswith('Monitoring heartbeat active'):
                    break
            if not startup_lines or not startup_lines[-1].startswith('Monitoring heartbeat active'):
                if process.poll() is None:
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        pass
                details = process.stderr.read() if process.poll() is not None else 'process remained alive without a startup line'
                raise RuntimeError(f'agent and visible status companion did not start successfully (output={startup_lines!r}): {details.strip()}')
            deadline = time.monotonic() + 20
            sample_count = 0
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError('agent exited before the first encrypted sample: ' + process.stderr.read())
                if database.exists():
                    report = _projection(database, private_key)
                    sample_count = len(report['samples'])
                    if sample_count >= 2:
                        break
                time.sleep(0.2)
            if sample_count < 2:
                raise RuntimeError('agent did not record two synthetic foreground samples')

            os.kill(process.pid, signal.SIGSTOP)
            time.sleep(9)
            os.kill(process.pid, signal.SIGCONT)
            deadline = time.monotonic() + 15
            gaps = []
            while time.monotonic() < deadline:
                report = _projection(database, private_key)
                gaps = report['gaps']
                if gaps:
                    break
                if process.poll() is not None:
                    raise RuntimeError('agent exited while checking its recorded coverage gap')
                time.sleep(0.2)
            if not gaps:
                raise RuntimeError('the resumed agent did not record the synthetic suspension gap')
            if any(name != 'Synthetic Study App' or bundle != 'org.example.synthetic-study'
                   for name, bundle in report['samples']):
                raise RuntimeError('the report contained an unexpected foreground value')
            if b'Synthetic Study App' in database.read_bytes() or b'org.example.synthetic-study' in database.read_bytes():
                raise RuntimeError('synthetic foreground plaintext was present in the database')

            process.terminate()
            process.wait(timeout=10)
            final = _projection(database, private_key)
            if not final['sessions'] or final['sessions'][0][2] is None:
                raise RuntimeError('agent termination did not record a closed session')
            gap_seconds = (datetime.fromisoformat(gaps[0][1]) - datetime.fromisoformat(gaps[0][0])).total_seconds()
            try:
                launchd_result = _validate_launchd(root, folder, foreground, status)
            except _AgentCleanupError as error:
                preserved = folder.with_name(f'{folder.name}-cleanup-{uuid.uuid4().hex}')
                folder.rename(preserved)
                raise RuntimeError(
                    f'{error}; temporary synthetic files are preserved at {preserved}. '
                    'Boot out the named validation job before deleting that directory.') from None
            return (f"Live Mac agent passed: {len(final['samples'])} synthetic app samples were encrypted, "
                    f"a {gap_seconds:.1f}-second coverage gap was recorded after process suspension, "
                    'and graceful termination closed the session. ' + launchd_result +
                    ' The disposable LaunchAgent was removed.')
        finally:
            if process.poll() is None:
                try:
                    os.kill(process.pid, signal.SIGCONT)
                except ProcessLookupError:
                    pass
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()


if __name__ == '__main__':
    print(validate())
