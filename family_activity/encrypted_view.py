"""Reconstruct an experimental encrypted event log in an in-memory database."""
from datetime import datetime
import hashlib
import re
from pathlib import Path
import sqlite3
from nacl.public import PrivateKey
from . import browser_channel, encrypted_store, store


def _valid_time(value):
    if not isinstance(value, str):
        return False
    try:
        return datetime.fromisoformat(value).utcoffset() is not None
    except ValueError:
        return False


def _network_intervals(value):
    if not isinstance(value, list) or len(value) > 16:
        raise ValueError('invalid network intervals')
    for row in value:
        if (not isinstance(row, list) or len(row) != 5
                or not _valid_time(row[0]) or not _valid_time(row[1])
                or not isinstance(row[2], str)
                or not all(isinstance(n, int) and not isinstance(n, bool) and 0 <= n <= 2**63-1 for n in row[3:])):
            raise ValueError('invalid network interval')
    return value


def open_projection(path, private_key):
    """Open an encrypted file read-only and reconstruct its contents in memory."""
    if not isinstance(private_key, PrivateKey):
        raise TypeError('private_key must be a PyNaCl PrivateKey')
    uri = Path(path).expanduser().resolve().as_uri() + '?mode=ro'
    source = sqlite3.connect(uri, uri=True, timeout=5)
    return _project(source, private_key)


def open_projection_bytes(data, private_key):
    """Validate an uploaded SQLite image before writing it to the filesystem."""
    if not isinstance(private_key, PrivateKey):
        raise TypeError('private_key must be a PyNaCl PrivateKey')
    source = sqlite3.connect(':memory:')
    try:
        source.deserialize(data)
    except BaseException:
        source.close()
        raise
    return _project(source, private_key)


def _project(source, private_key):
    """Reconstruct a consistent snapshot, failing closed on unsupported data."""
    memory = sqlite3.connect(':memory:')
    try:
        memory.execute('PRAGMA temp_store=MEMORY')
        store.initialize(memory)
        source.execute('BEGIN')
        fingerprint = hashlib.sha256(bytes(private_key.public_key)).hexdigest()
        if source.execute('SELECT fingerprint FROM key_commitment').fetchall() != [(fingerprint,)]:
            raise ValueError('incorrect parent key or invalid database')
        sessions = {}
        incomplete = False
        for ciphertext, in source.execute('SELECT ciphertext FROM encrypted_events ORDER BY id'):
            event = encrypted_store.open_event(private_key, ciphertext)
            typ, session, at = event.get('type'), event.get('session'), event.get('at')
            if not isinstance(session, str) or not session or not _valid_time(at):
                raise ValueError('invalid encrypted event')
            if typ == 'start':
                if session in sessions:
                    raise ValueError('duplicate session start')
                sessions[session] = store.start(memory, at)
                continue
            if typ not in {'heartbeat', 'stop', 'foreground', 'network', 'network_identity', 'website', 'tick', 'network_settings', 'gap'}:
                raise ValueError('unsupported encrypted event')
            if session not in sessions:
                # Retention may remove a start before newer records expire.
                incomplete = True
                sid = memory.execute('INSERT INTO sessions(started_at, heartbeat_at) VALUES (?, ?)',
                                     ('Start unavailable', at)).lastrowid
                sessions[session] = sid
            sid = sessions[session]
            if typ == 'tick':
                store.heartbeat(memory, sid, at)
                if 'application' in event:
                    app = event['application']
                    if app is not None and (not isinstance(app, list) or len(app) != 2 or not all(isinstance(x, str) for x in app)):
                        raise ValueError('invalid application observation')
                    store.record_foreground(memory, sid, app, at)
                if 'intervals' in event:
                    store.record_network(memory, sid, _network_intervals(event['intervals']))
            elif typ == 'heartbeat':
                store.heartbeat(memory, sid, at)
            elif typ == 'stop':
                store.stop(memory, sid, at)
            elif typ == 'foreground':
                app = event.get('application')
                if app is not None and (not isinstance(app, list) or len(app) != 2 or not all(isinstance(x, str) for x in app)):
                    raise ValueError('invalid application observation')
                store.record_foreground(memory, sid, app, at)
            elif typ == 'network':
                store.record_network(memory, sid, _network_intervals(event.get('intervals')))
            elif typ == 'network_settings':
                fields = ('dns_observed', 'proxy_indicator', 'vpn_indicator')
                if any(name not in event or (event[name] is not None and type(event[name]) is not bool) for name in fields):
                    raise ValueError('invalid network settings observation')
                memory.execute('INSERT INTO network_settings(session_id, sampled_at, dns_observed, proxy_indicator, vpn_indicator) VALUES (?, ?, ?, ?, ?)',
                               (sid, at, *(event[name] for name in fields)))
            elif typ == 'gap':
                start, end = event.get('from_at'), event.get('to_at')
                if not _valid_time(start) or not _valid_time(end) or datetime.fromisoformat(end) <= datetime.fromisoformat(start):
                    raise ValueError('invalid observation gap')
                store.record_gap(memory, sid, start, end)
            elif typ == 'website':
                domain = browser_channel.validate({'domain': event.get('domain')})
                memory.execute('INSERT INTO website_samples(session_id, sampled_at, domain) VALUES (?, ?, ?)', (sid, at, domain))
            else:
                token = event.get('identifier')
                if token is not None and (not isinstance(token, str) or not re.fullmatch(r'[0-9a-f]{64}', token)):
                    raise ValueError('invalid network identifier')
                memory.execute('INSERT INTO network_changes(session_id, sampled_at, identifier) VALUES (?, ?, ?)', (sid, at, token))
        return memory, incomplete
    except BaseException:
        memory.close()
        raise
    finally:
        source.close()
