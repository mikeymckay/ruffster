"""Parent-only encrypted names for pseudonymous monitored-computer IDs."""
import os
from pathlib import Path
import re
import tempfile

from nacl.public import PrivateKey

from .encrypted_store import open_event, seal_event

DEVICE_ID_RE = re.compile(r'(?:[0-9a-f]{32}|legacy)\Z')
MAX_LABEL_LENGTH = 48


def _validate(labels):
    if not isinstance(labels, dict) or len(labels) > 256:
        raise ValueError('invalid computer label file')
    for identifier, label in labels.items():
        if (not isinstance(identifier, str) or not DEVICE_ID_RE.fullmatch(identifier)
                or not isinstance(label, str) or not label.strip()
                or len(label) > MAX_LABEL_LENGTH
                or any(ord(char) < 32 or ord(char) == 127 for char in label)):
            raise ValueError('invalid computer label')
    return labels


def load(path, private):
    path = Path(path).expanduser()
    if not path.exists():
        return {}
    event = open_event(private, path.read_bytes())
    return _validate(event.get('labels'))


def set_label(path, private, identifier, label):
    if not isinstance(private, PrivateKey):
        raise TypeError('parent private key required')
    if not isinstance(identifier, str) or not DEVICE_ID_RE.fullmatch(identifier):
        raise ValueError('invalid computer identity')
    if not isinstance(label, str):
        raise ValueError('computer name must be text')
    label = label.strip()
    _validate({identifier: label})
    path = Path(path).expanduser()
    labels = load(path, private)
    labels[identifier] = label
    ciphertext = seal_event(private.public_key, {'labels': labels})
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.computer-labels-', dir=path.parent)
    try:
        if os.name == 'posix':
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(ciphertext)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name == 'posix':
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
