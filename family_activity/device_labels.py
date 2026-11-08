"""Append parent-chosen computer names as parent-key-encrypted report events."""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
import stat

from nacl.public import PrivateKey

from . import encrypted_store
from .encrypted_agent_store import EXPIRY_VERSION, LEGACY_EXPIRY_VERSION

DEVICE_ID_RE = re.compile(r'(?:[0-9a-f]{32}|legacy)\Z')
MAX_LABEL_LENGTH = 48


def _authentication_key(private):
    return hashlib.blake2b(bytes(private), digest_size=32, person=b'RuffsterLabels1').digest()


def authentication_tag(private, event):
    """Authenticate parent-only label fields; child machines hold only the public key."""
    fields = {name: event.get(name) for name in ('type', 'at', 'target_device_id', 'label')}
    payload = json.dumps(fields, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hmac.new(_authentication_key(private), payload, hashlib.sha256).hexdigest()


def validate_label(identifier, label):
    if not isinstance(identifier, str) or not DEVICE_ID_RE.fullmatch(identifier):
        raise ValueError('invalid computer identity')
    if (not isinstance(label, str) or not label.strip() or len(label) > MAX_LABEL_LENGTH
            or any(ord(char) < 32 or ord(char) == 127 for char in label)):
        raise ValueError('invalid computer label')
    return label.strip()


def set_label(database_path, private, identifier, label, retention_days=30):
    """Add an encrypted label event to an existing parent report database.

    Keeping names in the report makes the existing encrypted report backup a
    complete copy: restoring it on another parent computer restores the names.
    """
    if not isinstance(private, PrivateKey):
        raise TypeError('parent private key required')
    label = validate_label(identifier, label)
    if type(retention_days) is not int or not 1 <= retention_days <= 365:
        raise ValueError('invalid label retention')
    path = Path(database_path).expanduser()
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
        raise ValueError('encrypted parent report must be a regular file')
    database = sqlite3.connect(path, timeout=5)
    try:
        database.execute('PRAGMA busy_timeout=5000')
        database.execute('PRAGMA secure_delete=ON')
        database.execute('BEGIN IMMEDIATE')
        columns = {row[1] for row in database.execute('PRAGMA table_info(key_commitment)')}
        commitments = database.execute('SELECT fingerprint FROM key_commitment').fetchall()
        fingerprint = hashlib.sha256(bytes(private.public_key)).hexdigest()
        if commitments != [(fingerprint,)]:
            raise ValueError('parent report does not match its private key')
        if 'expiry_version' in columns:
            versions = database.execute('SELECT expiry_version FROM key_commitment').fetchall()
            if versions not in ([(EXPIRY_VERSION,)], [(LEGACY_EXPIRY_VERSION,)]):
                raise ValueError('unsupported encrypted report version')
            version = versions[0][0]
        else:
            version = LEGACY_EXPIRY_VERSION
        now = datetime.now(timezone.utc)
        event = {
            'type': 'device_label',
            'at': now.isoformat(timespec='microseconds'),
            'target_device_id': identifier,
            'label': label,
        }
        event['parent_auth'] = authentication_tag(private, event)
        ciphertext = encrypted_store.seal_event(private.public_key, event)
        expires = (now.date() + timedelta(days=retention_days)).isoformat()
        if version == LEGACY_EXPIRY_VERSION:
            expires = (now.date() + timedelta(days=retention_days + 1)).isoformat()
        database.execute(
            'INSERT INTO encrypted_events(expires_on, ciphertext) VALUES (?, ?)',
            (expires, ciphertext))
        database.commit()
    except BaseException:
        database.rollback()
        raise
    finally:
        database.close()
    if os.name == 'posix':
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
