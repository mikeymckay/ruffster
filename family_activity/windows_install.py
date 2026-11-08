"""Explicit per-user Windows Task Scheduler setup for the disclosed preview.

This registers a logon task for the current interactive account. It does not
install a machine-wide service and it cannot monitor before that user signs in.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

from . import locking, parent_settings, public_key_file, windows_task
from .key_vault import create_new

TASK_NAME = 'FamilyActivity-Agent'
FOLDER_NAME = 'Family Activity'
METADATA_NAME = 'windows-install.json'


def _run(args):
    return subprocess.run(args, capture_output=True, text=True, encoding='utf-8',
                          errors='replace', timeout=20, shell=False)


def _task_exe():
    root = os.environ.get('SystemRoot', r'C:\Windows')
    return str(Path(root) / 'System32' / 'schtasks.exe')


def _agent_running(database):
    """Check the agent's exclusive lock before and after asking Task Scheduler to stop it."""
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
        # Treat an unreadable lock as active so uninstall fails safely.
        return True


def _retained_event_count(database):
    """Count only unexpired encrypted rows; their content remains unreadable here."""
    database = Path(database)
    if not database.is_file():
        return 0
    uri = database.resolve().as_uri() + '?mode=ro'
    with sqlite3.connect(uri, uri=True, timeout=1) as db:
        return db.execute('SELECT COUNT(*) FROM encrypted_events WHERE expires_on > ?',
                          (datetime.now(timezone.utc).date().isoformat(),)).fetchone()[0]


def _wait_for_ready_session(database, previous_event_count, timeout=30):
    """Wait for a live agent that stored its first encrypted event after tray readiness."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            current_event_count = _retained_event_count(database)
        except (OSError, sqlite3.Error):
            current_event_count = None
        if current_event_count is not None and current_event_count > previous_event_count and _agent_running(database):
            return True
        time.sleep(0.2)
    return False


def _data_paths(local_app_data):
    base = Path(local_app_data)
    if not base.is_absolute():
        raise ValueError('LOCALAPPDATA must be an absolute path')
    folder = base / FOLDER_NAME
    return (folder, folder / 'parent.pub', folder / 'network.key',
            folder / 'activity.sqlite3', folder / METADATA_NAME)


def _is_linklike(path):
    """Recognize symlinks and Windows reparse points (including junctions)."""
    try:
        info = Path(path).lstat()
    except FileNotFoundError:
        return False
    attributes = getattr(info, 'st_file_attributes', 0)
    reparse_point = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse_point)


def _has_linklike_component(path, stop=None):
    """Check existing path components, so a redirected parent is caught too."""
    path = Path(path)
    stop = None if stop is None else Path(stop)
    current = path
    while True:
        if _is_linklike(current):
            return True
        if current == stop or current.parent == current:
            return False
        current = current.parent


def _identity(user, python_exe, source, status_exe, database, public_key, retention_days=30,
              packaged=False, network_key=None, foreground_helper=None,
              monitor_network=True, inspect_network_settings=True):
    identity = {
        'task_name': TASK_NAME,
        'user': user,
        'python': str(python_exe),
        'source': str(source),
        'status': str(status_exe),
        'database': str(database),
        'public_key': str(public_key),
        'retention_days': retention_days,
        'packaged': bool(packaged),
    }
    if network_key is not None:
        identity['network_key'] = str(network_key)
    if foreground_helper is not None:
        identity['foreground_helper'] = str(foreground_helper)
    if not monitor_network:
        identity['monitor_network'] = False
    if not inspect_network_settings:
        identity['inspect_network_settings'] = False
    return identity


def _matching_task(xml_text, expected):
    """Check the managed action and interactive logon trigger before removal."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml_text)
        ns = {'t': windows_task.NS}
        triggers = root.find('t:Triggers', ns)
        actions = root.find('t:Actions', ns)
        logons = [] if triggers is None else triggers.findall('t:LogonTrigger', ns)
        other_triggers = [] if triggers is None else list(triggers)
        execs = [] if actions is None else actions.findall('t:Exec', ns)
        action = execs[0] if len(execs) == 1 else None
        principal = root.find('t:Principals/t:Principal', ns)
        settings = root.find('t:Settings', ns)
        restart = None if settings is None else settings.find('t:RestartOnFailure', ns)
        trigger_user = None if not logons else logons[0].findtext('t:UserId', namespaces=ns)
        argv = ([] if expected.get('packaged', False) else ['-m', 'family_activity']) + [
            'agent', '--db', expected['database'],
            '--experimental-public-key', expected['public_key'],
            '--experimental-status-helper', expected['status'],
            '--retention-days', str(expected['retention_days']),
        ]
        if expected.get('foreground_helper'):
            argv += ['--experimental-foreground-helper', expected['foreground_helper']]
        else:
            argv += ['--experimental-windows-foreground']
        if expected.get('monitor_network', True):
            argv += ['--experimental-network']
        if expected.get('inspect_network_settings', True):
            argv += ['--experimental-network-settings']
        if expected.get('network_key'):
            argv += ['--experimental-network-key', expected['network_key']]
        arguments = subprocess.list2cmdline(argv)
        return (
            len(other_triggers) == 1 and len(logons) == 1 and
            len([] if actions is None else list(actions)) == 1 and
            trigger_user == expected['user'] and
            (principal is not None and principal.findtext('t:UserId', namespaces=ns) == expected['user']) and
            (principal is not None and principal.findtext('t:LogonType', namespaces=ns) == 'InteractiveToken') and
            (principal is not None and principal.findtext('t:RunLevel', namespaces=ns) == 'LeastPrivilege') and
            (logons[0].findtext('t:Enabled', namespaces=ns) in {'true', 'false'}) and
            logons[0].find('t:Delay', ns) is None and
            action is not None and action.findtext('t:Command', namespaces=ns) == expected['python'] and
            action.findtext('t:WorkingDirectory', namespaces=ns) == expected['source'] and
            action.findtext('t:Arguments', namespaces=ns) == arguments and
            restart is not None and restart.findtext('t:Interval', namespaces=ns) == 'PT1M' and
            restart.findtext('t:Count', namespaces=ns) == '10'
        )
    except (ET.ParseError, KeyError, TypeError, ValueError):
        return False


def install(public_key, python_exe, source_directory, status_exe, local_app_data=None,
            *, user=None, runner=_run, retention_days=30, packaged=False,
            foreground_helper=None, monitor_network=True, inspect_network_settings=True,
            readiness_check=None):
    """Register after the caller has disclosed monitoring and explicitly opted in.

    Existing installs and mismatched encrypted data are preserved. Monitoring
    runs only in the current user's interactive session and uses least privilege.
    """
    if sys.platform != 'win32':
        raise OSError('Windows installation is available only on Windows')
    parent_settings.validate_retention_days(retention_days)
    public = bytes(public_key_file.decode(Path(public_key).read_bytes(), allow_legacy=True))
    python_exe = Path(python_exe).resolve()
    source = Path(source_directory).resolve()
    status = Path(status_exe).resolve()
    if packaged:
        valid_runtime = (python_exe.name.lower() == 'familyactivitycore.exe' and
                         (source / 'FamilyActivityCore' / 'FamilyActivityCore.exe').resolve() == python_exe and
                         status.name.lower() == 'familyactivitysetup.exe' and
                         (source / 'FamilyActivitySetup.exe').resolve() == status)
    else:
        valid_runtime = python_exe.name.lower() == 'pythonw.exe' and (source / 'family_activity' / '__main__.py').is_file()
    if not valid_runtime:
        raise ValueError('application executable or runtime layout is invalid')
    if not python_exe.is_file() or not source.is_dir() or not status.is_file():
        raise ValueError('Python, application source, or visible status helper is unavailable')
    if inspect_network_settings and not monitor_network:
        raise ValueError('network settings observations require network sampling')
    if foreground_helper is not None:
        foreground_helper = Path(foreground_helper).resolve()
        if not foreground_helper.is_file():
            raise ValueError('foreground application helper is unavailable')
    local_app_data = local_app_data or os.environ.get('LOCALAPPDATA')
    if not local_app_data:
        raise ValueError('LOCALAPPDATA is unavailable')
    folder, key_path, network_key_path, database, metadata = _data_paths(local_app_data)
    if user is None:
        username = os.environ.get('USERNAME')
        domain = os.environ.get('USERDOMAIN')
        user = f'{domain}\\{username}' if domain and username else username
    if not isinstance(user, str) or not user.strip() or any(c in user for c in '\r\n\x00'):
        raise ValueError('the current interactive account could not be identified')
    sidecars = [Path(str(database) + suffix) for suffix in ('-wal', '-shm', '-journal', '.lock')]
    if any(_has_linklike_component(path, Path(local_app_data))
           for path in (folder, key_path, network_key_path, database, metadata, *sidecars)):
        raise ValueError('application data must not use symbolic links or reparse points')
    folder.mkdir(parents=True, exist_ok=True)
    if _has_linklike_component(folder, Path(local_app_data)):
        raise ValueError('application data folder must not use symbolic links or reparse points')
    if metadata.exists():
        raise FileExistsError('a Ruffster installation already exists')
    if key_path.exists() and key_path.read_bytes() != public:
        raise ValueError('existing data belongs to a different parent key')
    if database.exists():
        if database.is_symlink() or not key_path.exists():
            raise ValueError('existing data has no trusted associated parent public key')
        try:
            db = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)
            try:
                fingerprint = hashlib.sha256(public).hexdigest()
                if db.execute('SELECT fingerprint FROM key_commitment').fetchall() != [(fingerprint,)]:
                    raise ValueError('existing data does not match the parent key')
            finally:
                db.close()
        except sqlite3.Error:
            raise ValueError('existing data is not an encrypted activity database') from None

    previous_event_count = _retained_event_count(database)

    if network_key_path.exists() and (not network_key_path.is_file() or network_key_path.stat().st_size != 32):
        raise ValueError('existing network identifier key is invalid')
    active_network_key = network_key_path if monitor_network else None
    identity = _identity(user, python_exe, source, status, database, key_path, retention_days,
                         packaged, active_network_key, foreground_helper,
                         monitor_network, inspect_network_settings)
    definition = windows_task.task_xml(user, str(python_exe), str(database), str(key_path),
                                       str(status), str(source), retention_days, packaged,
                                       str(active_network_key) if active_network_key else None,
                                       str(foreground_helper) if foreground_helper else None,
                                       monitor_network, inspect_network_settings)
    task_path = Path(_task_exe())
    query = runner([str(task_path), '/Query', '/TN', TASK_NAME])
    if query.returncode == 0:
        raise FileExistsError('a task with the Ruffster name already exists')

    created_key = False
    created_network_key = False
    created_metadata = False
    temp_xml = None
    registration_uncertain = False
    try:
        if not key_path.exists():
            create_new(key_path, public)
            created_key = True
        if monitor_network and not network_key_path.exists():
            create_new(network_key_path, os.urandom(32))
            created_network_key = True
        info = {'version': 1, 'identity': identity}
        create_new(metadata, json.dumps(info, sort_keys=True).encode('utf-8'))
        created_metadata = True
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', newline='\n',
                                         prefix='family-activity-task-', suffix='.xml',
                                         dir=folder, delete=False) as stream:
            temp_xml = Path(stream.name)
            stream.write(definition)
            stream.flush()
            os.fsync(stream.fileno())
        result = runner([str(task_path), '/Create', '/TN', TASK_NAME, '/XML', str(temp_xml)])
        if result.returncode:
            live = runner([str(task_path), '/Query', '/TN', TASK_NAME, '/XML'])
            if live.returncode == 0:
                registration_uncertain = True
                raise RuntimeError('task registration state is uncertain; use explicit removal')
            raise RuntimeError('Task Scheduler could not register the agent')
        # From this point on, exceptions must preserve the metadata and keys so
        # the registered task can still be identified and removed safely.
        registration_uncertain = True
        started = runner([str(task_path), '/Run', '/TN', TASK_NAME])
        if started.returncode:
            raise RuntimeError('monitoring was registered, but Windows could not start it now; open Ruffster settings to check or remove the setup')
        ready = (readiness_check(database, previous_event_count) if readiness_check is not None
                 else _wait_for_ready_session(database, previous_event_count))
        if not ready:
            raise RuntimeError('monitoring was registered, but the tray indicator and encrypted agent session did not become ready in time; open Ruffster settings to check or remove the setup')
    except BaseException:
        # Keep metadata and keys whenever Task Scheduler may still own a task.
        if not registration_uncertain:
            if created_metadata:
                metadata.unlink(missing_ok=True)
            if created_key:
                key_path.unlink(missing_ok=True)
            if created_network_key:
                network_key_path.unlink(missing_ok=True)
        raise
    finally:
        if temp_xml is not None:
            temp_xml.unlink(missing_ok=True)
    return {'task_name': TASK_NAME, 'data_directory': str(folder)}


def uninstall(local_app_data=None, *, runner=_run, delete_data=False):
    """Remove only the matching per-user task; keep encrypted records and key."""
    if sys.platform != 'win32':
        raise OSError('Windows uninstallation is available only on Windows')
    local_app_data = local_app_data or os.environ.get('LOCALAPPDATA')
    if not local_app_data:
        raise ValueError('LOCALAPPDATA is unavailable')
    folder, key_path, network_key_path, database, metadata = _data_paths(local_app_data)
    # Validate every path before stopping the agent or changing Task Scheduler.
    if any(_has_linklike_component(path, Path(local_app_data))
           for path in (folder, metadata, key_path, network_key_path, database)):
        raise ValueError('application data must not use symbolic links or reparse points')
    files = [key_path, network_key_path, database] + [Path(str(database) + suffix)
                                   for suffix in ('-wal', '-shm', '-journal', '.lock')]
    if delete_data and any(_has_linklike_component(path, folder) for path in files):
        raise ValueError('application data contains a symbolic link or reparse point; refusing to delete it')
    info = json.loads(metadata.read_text('utf-8'))
    identity = info.get('identity')
    if info.get('version') != 1 or not isinstance(identity, dict) or identity.get('task_name') != TASK_NAME:
        raise ValueError('installation metadata is invalid')
    if identity.get('network_key') not in (None, str(network_key_path)):
        raise ValueError('installation metadata has an unexpected network key path')
    result = runner([_task_exe(), '/Query', '/TN', TASK_NAME, '/XML'])
    if result.returncode == 0:
        if not _matching_task(result.stdout, identity):
            raise ValueError('scheduled task changed; refusing to remove an unrecognized task')
        disabled = runner([_task_exe(), '/Change', '/TN', TASK_NAME, '/Disable'])
        if disabled.returncode:
            raise RuntimeError('the scheduled task could not be disabled; installation and encrypted data were retained')
        runner([_task_exe(), '/End', '/TN', TASK_NAME])
        deadline = time.monotonic() + 10
        while _agent_running(database) and time.monotonic() < deadline:
            time.sleep(.1)
        if _agent_running(database):
            raise RuntimeError('the running agent did not stop; installation and encrypted data were retained')
        removed = runner([_task_exe(), '/Delete', '/TN', TASK_NAME, '/F'])
        if removed.returncode:
            raise RuntimeError('could not stop and remove the scheduled task; installation was retained')
        check = runner([_task_exe(), '/Query', '/TN', TASK_NAME])
        if check.returncode == 0:
            raise RuntimeError('scheduled task is still registered; installation was retained')
    else:
        if _agent_running(database):
            raise RuntimeError('the agent is still running but its scheduled task could not be verified; installation was retained')
        raise RuntimeError('the scheduled task could not be verified; installation and encrypted data were retained')
    if delete_data:
        for path in files:
            path.unlink(missing_ok=True)
        try: folder.rmdir()
        except OSError: pass
    metadata.unlink()
    return {'task_removed': True, 'data_retained': str(folder), 'data_deleted': delete_data,
            'database_exists': database.exists(), 'public_key_exists': key_path.exists(),
            'network_key_exists': network_key_path.exists()}
