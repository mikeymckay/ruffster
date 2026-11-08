"""Build an opt-in per-user launchd definition without installing it."""
import os
import plistlib
import re


def agent_plist(label, python, working_directory, database, public_key, foreground_helper, status_helper, interval=15, throttle=10, frozen=False, retention_days=30, network_key=None, collect_network=True, collect_network_settings=True):
    """Return a launch agent plist for an interactive login session.

    It intentionally takes a public key only and does not install or load itself.
    KeepAlive restarts even after an intentional process exit until booted out.
    """
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', label or ''):
        raise ValueError('invalid launchd label')
    paths = (python, working_directory, database, public_key, foreground_helper, status_helper)
    if network_key is not None:
        paths += (network_key,)
    if not all(isinstance(path, str) and os.path.isabs(path) for path in paths):
        raise ValueError('all launchd paths must be absolute')
    if interval <= 0 or not 1 <= throttle <= 3600:
        raise ValueError('invalid interval or throttle')
    if type(collect_network) is not bool or type(collect_network_settings) is not bool:
        raise ValueError('network collection choices must be booleans')
    if collect_network_settings and not collect_network:
        raise ValueError('network settings collection requires network collection')
    from .parent_settings import validate_retention_days
    validate_retention_days(retention_days)
    prefix = [python, 'agent'] if frozen else [python, '-m', 'family_activity', 'agent']
    args = prefix + ['--db', database,
            '--interval', str(interval), '--experimental-public-key', public_key,
            '--retention-days', str(retention_days),
            '--experimental-foreground-helper', foreground_helper,
            '--experimental-status-helper', status_helper]
    if collect_network:
        args.append('--experimental-network')
    if collect_network_settings:
        args.append('--experimental-network-settings')
    if network_key is not None and collect_network:
        args += ['--experimental-network-key', network_key]
    return plistlib.dumps({'Label': label, 'ProgramArguments': args,
                           'WorkingDirectory': working_directory,
                           'LimitLoadToSessionType': 'Aqua', 'RunAtLoad': True,
                           'KeepAlive': True, 'ThrottleInterval': throttle})
