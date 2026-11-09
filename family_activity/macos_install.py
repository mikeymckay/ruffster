"""Explicit developer-only per-user launchd installation and removal.

The caller must obtain informed, child-visible disclosure before invoking this.
No installer runs automatically. Existing reports are never deleted here.
"""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import sqlite3
import subprocess
import time
from contextlib import closing
from datetime import datetime, timezone
from . import locking, macos_launchd, parent_settings, public_key_file
from .key_vault import create_new

DEFAULT_LABEL = 'org.familyactivity.agent'


def _run(args):
    return subprocess.run(args, capture_output=True, text=True, timeout=15)


def _check_process(domain, label, runner):
    return runner(['/bin/launchctl', 'print', f'{domain}/{label}']).returncode == 0


def _agent_running(database):
    """Check the agent's exclusive lock before treating a new sample as ready."""
    lock_path = Path(str(database) + '.lock')
    if not lock_path.exists():
        return False
    try:
        with lock_path.open('a+') as stream:
            try:
                locking.lock_file(stream)
            except BlockingIOError:
                return True
        return False
    except OSError:
        # An unreadable lock is not proof that the agent is stopped.
        return True


def _retained_event_count(database):
    """Count unexpired encrypted rows without reading any event contents."""
    database = Path(database)
    if not database.is_file():
        return 0
    uri = database.resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True, timeout=1)) as db:
        day = datetime.now(timezone.utc).date().isoformat()
        return db.execute('SELECT COUNT(*) FROM encrypted_events WHERE expires_on > ?',
                          (day,)).fetchone()[0]


def _wait_for_ready_session(database, previous_event_count, timeout=30):
    """Wait until launchd's live agent has saved a new encrypted sample."""
    if not isinstance(timeout, (int, float)) or not 0 < timeout <= 120:
        raise ValueError('readiness timeout must be greater than zero and at most 120 seconds')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            current_event_count = _retained_event_count(database)
        except (OSError, sqlite3.Error):
            current_event_count = None
        if (current_event_count is not None and current_event_count > previous_event_count
                and _agent_running(database)):
            return True
        time.sleep(0.2)
    return False


def _paths(home, label):
    if not isinstance(label, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', label):
        raise ValueError('invalid launchd label')
    home = Path(home)
    if not home.is_absolute(): raise ValueError('home must be absolute')
    home = home.resolve(strict=True)
    if not home.is_dir(): raise ValueError('home must be a directory')
    data = home / 'Library' / 'Application Support' / 'Family Activity'
    return (data, data / 'parent.pub', data / 'network.key', data / 'activity.sqlite3',
            data / 'install.json', home / 'Library' / 'LaunchAgents' / f'{label}.plist')


def _has_symlink_component(path, home):
    """Check each path component below the canonical home without following it."""
    try:
        parts = Path(path).relative_to(home).parts
    except ValueError:
        return True
    current = home
    for part in parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def install(public_key, python, source, foreground, status, home, uid, *, label=DEFAULT_LABEL, runner=_run, frozen=False, retention_days=30, collect_network=True, collect_network_settings=True, collect_process_network=False, readiness_check=None):
    """Install a launch agent only after the caller has obtained disclosure.

    Does not overwrite an existing agent, key, or report. Previously retained
    data may be reused only with its existing matching parent public key.
    """
    public = bytes(public_key_file.decode(Path(public_key).read_bytes(), allow_legacy=True))
    parent_settings.validate_retention_days(retention_days)
    data, key_path, network_key_path, database, metadata, plist = _paths(home, label)
    canonical_home = Path(home).resolve(strict=True)
    if (_has_symlink_component(data, canonical_home) or
        _has_symlink_component(plist, canonical_home)):
        raise ValueError('installation paths must not contain symbolic links')
    definition = macos_launchd.agent_plist(
        label, str(python), str(source), str(database), str(key_path),
        str(foreground), str(status), frozen=frozen, retention_days=retention_days,
        network_key=str(network_key_path), collect_network=collect_network,
        collect_network_settings=collect_network_settings,
        collect_process_network=collect_process_network,
        associated_bundle_id=macos_launchd.bundle_identifier_for_path(source))
    for path in (python, foreground, status):
        if not Path(path).is_file() or not os.access(path, os.X_OK): raise ValueError('required executable is unavailable')
    if not Path(source).is_dir() or (not frozen and not (Path(source) / 'family_activity' / '__main__.py').is_file()):
        raise ValueError('application runtime directory is unavailable')
    if plist.exists() or plist.is_symlink() or metadata.exists() or metadata.is_symlink(): raise FileExistsError('an installation already exists')
    if key_path.is_symlink(): raise ValueError('parent key path must not be a symbolic link')
    if key_path.exists() and key_path.read_bytes() != public: raise ValueError('existing data belongs to a different parent key')
    if network_key_path.is_symlink(): raise ValueError('network identifier key path must not be a symbolic link')
    if network_key_path.exists() and (not network_key_path.is_file() or network_key_path.stat().st_size != 32):
        raise ValueError('existing network identifier key is invalid')
    if database.exists():
        if database.is_symlink() or not key_path.exists(): raise ValueError('existing data has no trusted associated public key')
        db = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            fingerprint = hashlib.sha256(public).hexdigest()
            if db.execute('SELECT fingerprint FROM key_commitment').fetchall() != [(fingerprint,)]:
                raise ValueError('existing data does not match the parent key')
        except sqlite3.Error:
            raise ValueError('existing data is not an encrypted activity database') from None
        finally:
            db.close()
    previous_event_count = _retained_event_count(database)
    domain = f'gui/{uid}'
    if _check_process(domain, label, runner): raise FileExistsError('a launch agent with this label is already loaded')
    data.mkdir(mode=0o700, parents=True, exist_ok=True)
    if data.is_symlink() or (os.name == 'posix' and (data.stat().st_uid != os.getuid() or data.stat().st_mode & 0o077)):
        raise ValueError('application data directory must be private')
    plist.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if plist.parent.is_symlink(): raise ValueError('LaunchAgents directory must not be a symbolic link')
    created_key = False
    created_network_key = False
    created_plist = False
    created_metadata = False
    registered = False
    try:
        if not key_path.exists():
            create_new(key_path, public); created_key = True
        if not network_key_path.exists():
            create_new(network_key_path, os.urandom(32)); created_network_key = True
        create_new(plist, definition); created_plist = True
        info = {'version':1, 'label':label, 'plist_sha256':hashlib.sha256(definition).hexdigest(), 'public_sha256':hashlib.sha256(public).hexdigest()}
        create_new(metadata, json.dumps(info, sort_keys=True).encode()); created_metadata = True
        result = runner(['/bin/launchctl', 'bootstrap', domain, str(plist)])
        if result.returncode:
            raise RuntimeError('launchd could not start the agent')
        registered = True
        ready = (readiness_check(database, previous_event_count) if readiness_check is not None
                 else _wait_for_ready_session(database, previous_event_count))
        if not ready:
            raise RuntimeError('monitoring was registered, but the menu-bar status and first encrypted sample did not become ready in time; open Ruffster settings to check or remove setup')
    except BaseException:
        # If bootstrap reported failure but the label is live, leave the files
        # intact for explicit removal rather than creating an orphaned service.
        if registered:
            raise
        if created_plist and _check_process(domain, label, runner):
            raise RuntimeError('installation state is uncertain; remove the launch agent explicitly') from None
        if created_metadata: metadata.unlink(missing_ok=True)
        if created_plist: plist.unlink(missing_ok=True)
        if created_network_key: network_key_path.unlink(missing_ok=True)
        if created_key: key_path.unlink(missing_ok=True)
        raise
    return {'label':label, 'data_directory':str(data), 'plist':str(plist)}


def _running_pid(domain, label, runner):
    result = runner(['/bin/launchctl', 'print', f'{domain}/{label}'])
    output = getattr(result, 'stdout', '') or ''
    if result.returncode != 0 or 'state = running' not in output:
        return None
    match = re.search(r'^\s*pid = (\d+)$', output, re.MULTILINE)
    return int(match.group(1)) if match else None


def restart_after_update(home, uid, python, source, foreground, status, *,
                         label=DEFAULT_LABEL, runner=_run, timeout=20):
    """Restart an unchanged managed agent so it loads the replaced app runtime.

    The current app must be in the same location used by the installed agent.
    Existing collection arguments, parent key, encrypted report, and retention
    settings are left untouched.
    """
    if not 1 <= timeout <= 60:
        raise ValueError('restart timeout must be 1 to 60 seconds')
    data, key_path, network_key_path, database, metadata, plist = _paths(home, label)
    canonical_home = Path(home).resolve(strict=True)
    if (_has_symlink_component(data, canonical_home) or
            _has_symlink_component(plist, canonical_home) or
            metadata.is_symlink() or key_path.is_symlink() or network_key_path.is_symlink() or
            database.is_symlink()):
        raise ValueError('installation paths must not contain symbolic links')
    try:
        info = json.loads(metadata.read_text('utf-8'))
        definition_bytes = plist.read_bytes()
        definition = plistlib.loads(definition_bytes)
        public = key_path.read_bytes()
        public_key_file.decode(public, allow_legacy=True)
    except (OSError, ValueError, TypeError, json.JSONDecodeError, plistlib.InvalidFileException):
        raise ValueError('managed installation files are missing or invalid') from None
    if (not isinstance(info, dict) or not isinstance(definition, dict) or
            info.get('version') != 1 or info.get('label') != label or
            info.get('plist_sha256') != hashlib.sha256(definition_bytes).hexdigest() or
            info.get('public_sha256') != hashlib.sha256(public).hexdigest() or
            definition.get('Label') != label):
        raise ValueError('installation changed; refusing to restart it automatically')
    source = str(source)
    python = str(python)
    foreground = str(foreground)
    status = str(status)
    arguments = definition.get('ProgramArguments')
    if (not isinstance(arguments, list) or not arguments or arguments[0] != python or
            definition.get('WorkingDirectory') != source):
        raise ValueError('open the updated app from the same location as the existing installation')

    def value_after(option):
        try:
            return arguments[arguments.index(option) + 1]
        except (ValueError, IndexError):
            return None

    if (value_after('--db') != str(database) or value_after('--experimental-public-key') != str(key_path) or
            value_after('--experimental-foreground-helper') != foreground or
            value_after('--experimental-status-helper') != status):
        raise ValueError('the installed agent does not match this app location')
    for executable in (python, foreground, status):
        if not Path(executable).is_file() or not os.access(executable, os.X_OK):
            raise ValueError('the updated app or a required helper is unavailable')
    if not Path(source).is_dir():
        raise ValueError('the updated app runtime is unavailable')

    domain = f'gui/{uid}'
    if not _check_process(domain, label, runner):
        raise ValueError('the managed agent is not registered for this account')
    previous_pid = _running_pid(domain, label, runner)
    result = runner(['/bin/launchctl', 'kickstart', '-k', f'{domain}/{label}'])
    if result.returncode:
        raise RuntimeError('launchd could not restart the agent; the encrypted report was left untouched')
    deadline = time.monotonic() + timeout
    current_pid = None
    while time.monotonic() < deadline:
        current_pid = _running_pid(domain, label, runner)
        if current_pid is not None and current_pid != previous_pid:
            return {'label': label, 'previous_pid': previous_pid, 'pid': current_pid,
                    'data_directory': str(data)}
        time.sleep(0.1)
    raise RuntimeError('the updated agent did not report a new running process; its data was retained')


def uninstall(home, uid, *, label=DEFAULT_LABEL, runner=_run, delete_data=False):
    """Stop and remove only an unchanged managed agent; retain encrypted data."""
    data, key_path, network_key_path, database, metadata, plist = _paths(home, label)
    canonical_home = Path(home).resolve(strict=True)
    if (_has_symlink_component(data, canonical_home) or
        _has_symlink_component(plist, canonical_home)):
        raise ValueError('installation paths must not contain symbolic links')
    if metadata.is_symlink() or plist.is_symlink(): raise ValueError('installation metadata must not be symbolic links')
    info = json.loads(metadata.read_text('utf-8'))
    definition = plist.read_bytes()
    if (info.get('version') != 1 or info.get('label') != label or
        info.get('plist_sha256') != hashlib.sha256(definition).hexdigest() or
        plistlib.loads(definition).get('Label') != label):
        raise ValueError('agent definition changed; refusing to remove it automatically')
    files_to_delete = None
    if delete_data:
        files_to_delete = [key_path, network_key_path, database, Path(str(database) + '.device-id')] + [Path(str(database) + suffix)
                                        for suffix in ('-wal', '-shm', '-journal', '.lock')]
        if any(path.is_symlink() for path in files_to_delete):
            raise ValueError('application data contains a symbolic link; refusing to delete it')
    domain = f'gui/{uid}'
    if _check_process(domain, label, runner):
        result = runner(['/bin/launchctl', 'bootout', domain, str(plist)])
        if result.returncode or _check_process(domain, label, runner):
            raise RuntimeError('could not stop the agent; installation was retained')
    deleted = False
    if delete_data:
        for path in files_to_delete:
            path.unlink(missing_ok=True)
        try: data.rmdir()
        except OSError: pass
        deleted = True
    plist.unlink()
    metadata.unlink()
    return {'data_retained': str(data), 'data_deleted': deleted,
            'database_exists': database.exists(), 'public_key_exists': key_path.exists(),
            'network_key_exists': network_key_path.exists()}
