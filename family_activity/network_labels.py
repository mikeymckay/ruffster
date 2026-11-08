"""Parent-held encrypted labels for pseudonymous network identifiers."""
import os
from pathlib import Path
import re
import tempfile
from nacl.public import PrivateKey
from .encrypted_store import open_event, seal_event

ALLOWED = {'home', 'school', 'other'}


def _validate(labels):
    if not isinstance(labels, dict):
        raise ValueError('invalid network label file')
    if not all(isinstance(key, str) and re.fullmatch(r'[0-9a-f]{64}', key)
               and value in ALLOWED for key, value in labels.items()):
        raise ValueError('invalid network label')
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
    if label is None:
        _validate({identifier: 'other'})
    else:
        _validate({identifier: label})
    path = Path(path).expanduser()
    labels = load(path, private)
    if label is None:
        labels.pop(identifier, None)
    else:
        labels[identifier] = label
    ciphertext = seal_event(private.public_key, {'labels': labels})
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix='.family-labels-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(ciphertext); f.flush(); os.fsync(f.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
