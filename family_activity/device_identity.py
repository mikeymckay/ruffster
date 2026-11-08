"""Stable, random per-database identity used only inside encrypted events."""
import os
from pathlib import Path
import re
import uuid


IDENTITY_RE = re.compile(r'[0-9a-f]{32}\n?\Z')


def identity_path(database_path):
    """Return the private sidecar path; report exports contain only ciphertext."""
    return Path(str(Path(database_path).expanduser()) + '.device-id')


def _read(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        raise
    if not path.is_file() or path.is_symlink():
        raise ValueError('device identity must be a regular file')
    if info.st_size > 33:
        raise ValueError('device identity file is invalid')
    value = path.read_text(encoding='ascii')
    if not IDENTITY_RE.fullmatch(value):
        raise ValueError('device identity file is invalid')
    return value.strip()


def load_or_create(database_path):
    """Load or atomically create a stable random identifier next to an agent DB."""
    path = identity_path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return _read(path)
    except FileNotFoundError:
        pass
    value = uuid.uuid4().hex
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return _read(path)
    try:
        with os.fdopen(descriptor, 'w', encoding='ascii', newline='\n') as stream:
            stream.write(value + '\n')
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return value
