"""Experimental encrypted agent event log with day-granularity retention metadata.

Public-key encryption is write-only; no private key is used on this device.
The expiry date is deliberately visible to allow autonomous retention and leaks
an approximate recording day. This format does not authenticate the writer or
protect against deleting, replacing, or replaying events.
"""
from datetime import date, datetime, timezone, timedelta
import hashlib
import os
from pathlib import Path
import sqlite3
import uuid
from nacl.public import PublicKey
from . import device_identity, encrypted_store, store

LEGACY_EXPIRY_VERSION = 1
EXPIRY_VERSION = 2


class EncryptedAgentStore:
    def __init__(self, path, public_key, retention_days):
        if not isinstance(public_key, PublicKey):
            raise TypeError('public_key must be a PyNaCl PublicKey')
        if retention_days < 1:
            raise ValueError('retention_days must be positive')
        path = Path(path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        self.db = sqlite3.connect(path, timeout=5)
        try:
            self.db.execute('PRAGMA busy_timeout=5000')
            self.db.execute('PRAGMA secure_delete=ON')
            tables = {row[0] for row in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables - {'encrypted_events', 'key_commitment'}:
                raise ValueError('database is not a dedicated encrypted agent store')
            self.db.execute('CREATE TABLE IF NOT EXISTS encrypted_events (id INTEGER PRIMARY KEY, expires_on TEXT NOT NULL, ciphertext BLOB NOT NULL)')
            fingerprint = hashlib.sha256(bytes(public_key)).hexdigest()
            if 'key_commitment' not in tables:
                self.db.execute('CREATE TABLE key_commitment (fingerprint TEXT NOT NULL, expiry_version INTEGER NOT NULL)')
                self.db.execute('INSERT INTO key_commitment VALUES (?, ?)', (fingerprint, EXPIRY_VERSION))
            else:
                columns = {row[1] for row in self.db.execute('PRAGMA table_info(key_commitment)')}
                existing = self.db.execute('SELECT fingerprint FROM key_commitment').fetchall()
                if existing and existing != [(fingerprint,)]:
                    raise ValueError('public key does not match this encrypted database')
                if 'expiry_version' not in columns:
                    self.db.execute('ALTER TABLE key_commitment ADD COLUMN expiry_version INTEGER NOT NULL DEFAULT 1')
                if not existing:
                    self.db.execute('INSERT INTO key_commitment (fingerprint, expiry_version) VALUES (?, ?)',
                                    (fingerprint, EXPIRY_VERSION))
                else:
                    versions = self.db.execute('SELECT expiry_version FROM key_commitment').fetchall()
                    if versions == [(LEGACY_EXPIRY_VERSION,)]:
                        expiries = self.db.execute('SELECT DISTINCT expires_on FROM encrypted_events').fetchall()
                        for (expiry,) in expiries:
                            if not isinstance(expiry, str):
                                raise ValueError('invalid encrypted record expiration day')
                            try:
                                parsed = date.fromisoformat(expiry)
                            except ValueError:
                                raise ValueError('invalid encrypted record expiration day') from None
                            if parsed.isoformat() != expiry:
                                raise ValueError('invalid encrypted record expiration day')
                            try:
                                corrected = (parsed - timedelta(days=1)).isoformat()
                            except OverflowError:
                                raise ValueError('invalid encrypted record expiration day') from None
                            self.db.execute('UPDATE encrypted_events SET expires_on = ? WHERE expires_on = ?', (corrected, expiry))
                        self.db.execute('UPDATE key_commitment SET expiry_version = ?', (EXPIRY_VERSION,))
                    elif versions != [(EXPIRY_VERSION,)]:
                        raise ValueError('unsupported encrypted record expiry version')
            self.db.commit()
        except BaseException:
            self.db.close()
            raise
        self.public_key = public_key
        self.retention_days = retention_days
        self.session_id = uuid.uuid4().hex
        self.device_id = device_identity.load_or_create(path)

    def event(self, event_type, **fields):
        now = datetime.now(timezone.utc)
        # Date-only expiry bounds retention to the selected number of days. The
        # record may be removed earlier that day because precise event timestamps
        # are encrypted and cannot be inspected by the child-side agent.
        expires_on = (now.date() + timedelta(days=self.retention_days)).isoformat()
        event = {'type': event_type, **fields}
        event['session'] = self.session_id
        event['device_id'] = self.device_id
        event['at'] = fields.get('at', now.isoformat(timespec='microseconds'))
        ciphertext = encrypted_store.seal_event(self.public_key, event)
        with self.db:
            self.db.execute('INSERT INTO encrypted_events(expires_on, ciphertext) VALUES (?, ?)', (expires_on, ciphertext))

    def prune(self, reference=None):
        now = reference or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError('reference must be timezone-aware')
        day = now.astimezone(timezone.utc).date().isoformat()
        with self.db:
            self.db.execute('DELETE FROM encrypted_events WHERE expires_on <= ?', (day,))

    def close(self):
        self.db.close()
