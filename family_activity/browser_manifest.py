"""Generate developer-only Chromium native-messaging files; never install them."""
import json
import os
import re
import shlex


def host_manifest(host_path, extension_id):
    if not os.path.isabs(host_path) or not re.fullmatch(r'[a-p]{32}', extension_id):
        raise ValueError('absolute host path and exact Chromium extension ID required')
    return json.dumps({'name': 'org.familyactivity.browser',
                       'description': 'Ruffster domain-only browser bridge',
                       'path': host_path, 'type': 'stdio',
                       'allowed_origins': [f'chrome-extension://{extension_id}/']}, indent=2)


def unix_launcher(python, project_dir, socket_path):
    if not all(os.path.isabs(path) for path in (python, project_dir, socket_path)):
        raise ValueError('launcher paths must be absolute')
    return ('#!/bin/sh\n'
            'export FAMILY_ACTIVITY_BROWSER_SOCKET=' + shlex.quote(socket_path) + '\n'
            'export PYTHONPATH=' + shlex.quote(project_dir) + '\n'
            'exec ' + shlex.quote(python) + ' -m family_activity.browser_host\n')
