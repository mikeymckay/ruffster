"""Small local parent-app preferences; contains no child activity data."""
import json
import os
from pathlib import Path
import tempfile

RETENTION_OPTIONS = (7, 30, 90, 180, 365)
DEFAULT_RETENTION_DAYS = 30


def validate_retention_days(value):
    if type(value) is not int or value not in RETENTION_OPTIONS:
        raise ValueError('choose a supported report retention period')
    return value


def _load(path):
    try:
        content = json.loads(Path(path).read_text('utf-8'))
        if not isinstance(content, dict):
            raise ValueError('invalid parent settings')
        return {
            'retention_days': validate_retention_days(content.get('retention_days')),
            'backup_confirmed': content.get('backup_confirmed') is True,
        }
    except (OSError, ValueError, TypeError):
        return {'retention_days': DEFAULT_RETENTION_DAYS, 'backup_confirmed': False}


def load_retention(path):
    return _load(path)['retention_days']


def load_backup_confirmation(path):
    return _load(path)['backup_confirmed']


def _save(path, settings):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.parent-settings-', dir=path.parent)
    try:
        if os.name == 'posix':
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(settings, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name == 'posix':
            fd = os.open(path.parent, os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
    except BaseException:
        try: os.close(fd)
        except OSError: pass
        try: os.unlink(temporary)
        except FileNotFoundError: pass
        raise


def save_retention(path, days):
    days = validate_retention_days(days)
    settings = _load(path)
    settings['retention_days'] = days
    _save(path, settings)


def save_backup_confirmation(path, confirmed):
    if type(confirmed) is not bool:
        raise ValueError('backup confirmation must be a boolean')
    settings = _load(path)
    settings['backup_confirmed'] = confirmed
    _save(path, settings)
