"""Sealed-box record encoding shared by the encrypted agent and parent reader.

The writer needs only a parent's public key. Only someone with the matching
private key can open a record. Sealed boxes do not authenticate the sender or
protect against removal, replay, reordering, or a compromised writing machine.
"""
import json
import os
from pathlib import Path
import sqlite3
import struct
from nacl.public import PublicKey, PrivateKey, SealedBox

PAYLOAD_SIZES = (256, 512, 1024, 2048, 4096)
CIPHERTEXT_SIZES = frozenset(size + 48 for size in PAYLOAD_SIZES)
FORMAT_VERSION = 1


def connect(path):
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        pass
    else:
        os.close(fd)
    db = sqlite3.connect(path, timeout=5)
    db.execute('PRAGMA busy_timeout=5000')
    db.execute('PRAGMA secure_delete=ON')
    db.execute('CREATE TABLE IF NOT EXISTS sealed_events (id INTEGER PRIMARY KEY, ciphertext BLOB NOT NULL)')
    db.commit()
    return db


def seal_event(public_key, event):
    """Pad to a size bucket before encryption; old 4096-byte records remain readable."""
    if not isinstance(public_key, PublicKey):
        raise TypeError('public_key must be a PyNaCl PublicKey')
    if not isinstance(event, dict):
        raise TypeError('event must be a JSON object')
    encoded = json.dumps({'version': FORMAT_VERSION, 'event': event}, ensure_ascii=False,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    size = next((size for size in PAYLOAD_SIZES if len(encoded) + 4 <= size), None)
    if size is None:
        raise ValueError('event exceeds encrypted record size')
    payload = struct.pack('>I', len(encoded)) + encoded
    payload += bytes(size - len(payload))
    return SealedBox(public_key).encrypt(payload)


def open_event(private_key, ciphertext):
    if not isinstance(private_key, PrivateKey):
        raise TypeError('private_key must be a PyNaCl PrivateKey')
    plaintext = SealedBox(private_key).decrypt(ciphertext)
    if len(plaintext) not in PAYLOAD_SIZES:
        raise ValueError('invalid encrypted record size')
    length = struct.unpack('>I', plaintext[:4])[0]
    if length > len(plaintext) - 4:
        raise ValueError('invalid encrypted record length')
    record = json.loads(plaintext[4:4 + length].decode('utf-8'))
    if not isinstance(record, dict) or record.get('version') != FORMAT_VERSION or not isinstance(record.get('event'), dict):
        raise ValueError('unsupported encrypted record format')
    return record['event']


def append(db, public_key, event):
    ciphertext = seal_event(public_key, event)
    with db:
        return db.execute('INSERT INTO sealed_events(ciphertext) VALUES (?)', (ciphertext,)).lastrowid


def read(db, private_key):
    """Yield events in insertion order; fail closed on corrupt or wrong-key data."""
    for ciphertext, in db.execute('SELECT ciphertext FROM sealed_events ORDER BY id'):
        yield open_event(private_key, ciphertext)
