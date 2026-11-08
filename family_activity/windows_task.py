"""Generate the experimental per-user Task Scheduler manifest."""
import ntpath
import os
import subprocess
import xml.etree.ElementTree as ET

NS = 'http://schemas.microsoft.com/windows/2004/02/mit/task'
ET.register_namespace('', NS)


def _node(parent, name, text=None):
    child = ET.SubElement(parent, f'{{{NS}}}{name}')
    child.text = text
    return child


def _absolute(path):
    # os.path follows the host platform. This also lets unit tests exercise
    # task generation with temporary paths on non-Windows development hosts.
    return ntpath.isabs(path) or os.path.isabs(path)


def task_xml(user, python_exe, database, public_key, status_exe, working_directory=None, retention_days=30,
             packaged=False, network_key=None, foreground_helper=None, monitor_network=True,
             inspect_network_settings=True):
    """Create a logon task with bounded failure restarts, for later review."""
    paths = (python_exe, database, public_key, status_exe) + \
        ((working_directory,) if working_directory else ()) + ((foreground_helper,) if foreground_helper else ())
    if not user or not all(_absolute(p) for p in paths):
        raise ValueError('user and absolute Windows paths are required')
    if foreground_helper is not None and not _absolute(foreground_helper):
        raise ValueError('foreground helper path must be absolute')
    if inspect_network_settings and not monitor_network:
        raise ValueError('network settings observations require network sampling')
    if network_key is not None and not monitor_network:
        raise ValueError('network identifier key requires network sampling')
    from .parent_settings import validate_retention_days
    validate_retention_days(retention_days)
    task = ET.Element(f'{{{NS}}}Task', {'version': '1.4'})
    registration = _node(task, 'RegistrationInfo')
    _node(registration, 'Description', 'Family Activity disclosed experimental monitoring')
    triggers = _node(task, 'Triggers')
    logon = _node(triggers, 'LogonTrigger')
    _node(logon, 'Enabled', 'true')
    _node(logon, 'UserId', user)
    principals = _node(task, 'Principals')
    principal = ET.SubElement(principals, f'{{{NS}}}Principal', {'id': 'Author'})
    _node(principal, 'UserId', user)
    _node(principal, 'LogonType', 'InteractiveToken')
    _node(principal, 'RunLevel', 'LeastPrivilege')
    settings = _node(task, 'Settings')
    _node(settings, 'MultipleInstancesPolicy', 'IgnoreNew')
    _node(settings, 'DisallowStartIfOnBatteries', 'false')
    _node(settings, 'StopIfGoingOnBatteries', 'false')
    _node(settings, 'ExecutionTimeLimit', 'PT0S')
    restart = _node(settings, 'RestartOnFailure')
    _node(restart, 'Interval', 'PT1M')
    _node(restart, 'Count', '10')
    actions = ET.SubElement(task, f'{{{NS}}}Actions', {'Context': 'Author'})
    action = _node(actions, 'Exec')
    _node(action, 'Command', python_exe)
    if working_directory:
        _node(action, 'WorkingDirectory', working_directory)
    args = ([] if packaged else ['-m', 'family_activity']) + ['agent', '--db', database,
            '--experimental-public-key', public_key, '--experimental-status-helper', status_exe,
            '--retention-days', str(retention_days)]
    if foreground_helper is None:
        args += ['--experimental-windows-foreground']
    else:
        args += ['--experimental-foreground-helper', foreground_helper]
    if monitor_network:
        args += ['--experimental-network']
    if inspect_network_settings:
        args += ['--experimental-network-settings']
    if network_key is not None:
        if not _absolute(network_key):
            raise ValueError('network identifier key path must be absolute')
        args += ['--experimental-network-key', network_key]
    _node(action, 'Arguments', subprocess.list2cmdline(args))
    return ET.tostring(task, encoding='unicode', xml_declaration=True)
