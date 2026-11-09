"""Exercise the real per-user install/uninstall path without collecting activity.

Run on a logged-in Mac from an environment with the project dependencies
installed. The disposable LaunchAgent runs only a shell wrapper that sleeps.
No Family Activity collector, foreground helper, or status UI is started.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

from nacl.public import PrivateKey

from family_activity import macos_install, public_key_file


def _launchctl(*arguments):
    return subprocess.run(['/bin/launchctl', *arguments], capture_output=True,
                          text=True, timeout=15)


def _service_state(domain, label):
    return _launchctl('print', f'{domain}/{label}')


def _running_pid(state):
    if state.returncode != 0 or 'state = running' not in state.stdout:
        return None
    match = re.search(r'^\s*pid = (\d+)$', state.stdout, re.MULTILINE)
    return int(match.group(1)) if match else None


def _bootout(domain, label, plist):
    state = _service_state(domain, label)
    if state.returncode == 0:
        result = _launchctl('bootout', domain, str(plist))
        if result.returncode != 0:
            raise RuntimeError('could not stop the disposable launch agent: ' + result.stderr.strip())
        if _service_state(domain, label).returncode == 0:
            raise RuntimeError('the disposable launch agent remains registered')


def validate():
    if sys.platform != 'darwin':
        raise SystemExit('Run this validation on macOS.')
    uid = os.getuid()
    domain = f'gui/{uid}'
    label = f'org.familyactivity.validation.{uuid.uuid4().hex}'
    root = Path(tempfile.mkdtemp(prefix='family-activity-install-check-'))
    home = root / 'home'
    plist = home / 'Library' / 'LaunchAgents' / f'{label}.plist'
    installed = False
    try:
        home.mkdir()
        source = root / 'runtime'
        package = source / 'family_activity'
        package.mkdir(parents=True)
        (package / '__main__.py').write_text('# Disposable launchd fixture.\n', encoding='utf-8')
        sleeper = root / 'non-collecting-agent'
        sleeper.write_text('#!/bin/sh\nexec /bin/sleep 60\n', encoding='utf-8')
        sleeper.chmod(0o700)
        public_key = root / 'parent.pub'
        public_key.write_bytes(public_key_file.encode(PrivateKey.generate().public_key))
        result = macos_install.install(public_key, sleeper, source, sleeper, sleeper,
                                       home, uid, label=label,
                                       readiness_check=lambda database, previous_count: True)
        installed = True
        deadline = time.monotonic() + 20
        state = _service_state(domain, label)
        first_pid = _running_pid(state)
        while first_pid is None:
            if time.monotonic() >= deadline:
                raise RuntimeError('the disposable launch agent did not start: ' + state.stdout.strip())
            time.sleep(0.1)
            state = _service_state(domain, label)
            first_pid = _running_pid(state)

        killed = _launchctl('kill', 'SIGKILL', f'{domain}/{label}')
        if killed.returncode != 0:
            raise RuntimeError('could not stop the first disposable agent process: ' + killed.stderr.strip())
        deadline = time.monotonic() + 25
        restarted_pid = None
        while restarted_pid is None or restarted_pid == first_pid:
            if time.monotonic() >= deadline:
                raise RuntimeError('launchd did not restart the disposable agent after SIGKILL')
            time.sleep(0.1)
            restarted_pid = _running_pid(_service_state(domain, label))

        data = Path(result['data_directory'])
        parent_copy = data / 'parent.pub'
        device_key = data / 'network.key'
        if not parent_copy.is_file() or not device_key.is_file() or device_key.stat().st_size != 32:
            raise RuntimeError('the installer did not create the expected setup files')

        outcome = macos_install.uninstall(home, uid, label=label)
        installed = False
        if outcome['data_deleted'] or not outcome['public_key_exists'] or not outcome['network_key_exists']:
            raise RuntimeError('uninstall did not retain the local setup data')
        if _service_state(domain, label).returncode == 0:
            raise RuntimeError('uninstall left the launch agent registered')
        process = subprocess.run(['/bin/ps', '-p', str(restarted_pid)], capture_output=True, text=True)
        if process.returncode == 0:
            raise RuntimeError('uninstall left the disposable process running')
        return 'Live launchd startup/restart/uninstall passed: the harmless job restarted after SIGKILL, then stopped with local setup data retained.'
    finally:
        _bootout(domain, label, plist)
        if installed:
            try:
                macos_install.uninstall(home, uid, label=label, delete_data=True)
            except (OSError, ValueError, RuntimeError):
                pass
        shutil.rmtree(root, ignore_errors=False)


if __name__ == '__main__':
    print(validate())
