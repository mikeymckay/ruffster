"""Reconstruct an experimental encrypted event log in an in-memory database."""
from datetime import datetime
import hashlib
import hmac
import re
from pathlib import Path
import sqlite3
from nacl.public import PrivateKey
from . import browser_channel, device_labels, encrypted_store, store


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


def _device_id(event):
    value = event.get('device_id', 'legacy')
    if value == 'legacy':
        return value
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{32}', value):
        raise ValueError('invalid encrypted device identity')
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
        memory.execute('CREATE TABLE device_labels (device_id TEXT PRIMARY KEY, label TEXT NOT NULL, updated_at TEXT NOT NULL)')
        source.execute('BEGIN')
        fingerprint = hashlib.sha256(bytes(private_key.public_key)).hexdigest()
        if source.execute('SELECT fingerprint FROM key_commitment').fetchall() != [(fingerprint,)]:
            raise ValueError('incorrect parent key or invalid database')
        sessions = {}
        process_network_states = {}
        incomplete = False
        for ciphertext, in source.execute('SELECT ciphertext FROM encrypted_events ORDER BY id'):
            event = encrypted_store.open_event(private_key, ciphertext)
            typ, session, at = event.get('type'), event.get('session'), event.get('at')
            if typ == 'device_label':
                authentication = event.get('parent_auth')
                try:
                    expected_authentication = device_labels.authentication_tag(private_key, event)
                except (TypeError, ValueError, UnicodeError):
                    continue
                if (not isinstance(authentication, str) or
                        not hmac.compare_digest(authentication, expected_authentication)):
                    # Child machines can encrypt with the parent's public key,
                    # but cannot authenticate a parent-chosen computer name.
                    continue
                target = event.get('target_device_id')
                label = event.get('label')
                if (not _valid_time(at) or not isinstance(target, str)
                        or (target != 'legacy' and not re.fullmatch(r'[0-9a-f]{32}', target))
                        or not isinstance(label, str) or not label.strip() or len(label) > 48
                        or any(ord(char) < 32 or ord(char) == 127 for char in label)):
                    raise ValueError('invalid encrypted computer label')
                memory.execute(
                    'INSERT INTO device_labels(device_id,label,updated_at) VALUES (?,?,?) '
                    'ON CONFLICT(device_id) DO UPDATE SET label=excluded.label, updated_at=excluded.updated_at '
                    'WHERE excluded.updated_at >= device_labels.updated_at',
                    (target, label.strip(), at))
                continue
            device_id = _device_id(event)
            session_key = (device_id, session)
            if not isinstance(session, str) or not session or not _valid_time(at):
                raise ValueError('invalid encrypted event')
            if typ == 'start':
                if session_key in sessions:
                    raise ValueError('duplicate session start')
                sessions[session_key] = store.start(memory, at, device_id)
                process_network_states[session_key] = None
                continue
            if typ not in {'heartbeat', 'stop', 'foreground', 'network', 'network_identity', 'website', 'tick', 'network_settings', 'gap', 'process_network', 'process_network_status'}:
                if typ == 'restart_marker' and session_key in sessions:
                    memory.execute('UPDATE sessions SET restarted_after_unclean_exit = 1 WHERE id = ?',
                                   (sessions[session_key],))
                    continue
                raise ValueError('unsupported encrypted event')
            if session_key not in sessions:
                # Retention may remove a start before newer records expire.
                incomplete = True
                sid = memory.execute('INSERT INTO sessions(started_at, heartbeat_at) VALUES (?, ?)',
                                     ('Start unavailable', at)).lastrowid
                memory.execute('UPDATE sessions SET device_id = ? WHERE id = ?', (device_id, sid))
                sessions[session_key] = sid
            sid = sessions[session_key]
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
            elif typ == 'process_network_status':
                state = event.get('state')
                if (state not in {'enabled', 'disabled', 'unavailable', 'unsupported'}
                        or process_network_states.get(session_key) in {'disabled', 'unavailable', 'unsupported'}):
                    raise ValueError('invalid process network status')
                process_network_states[session_key] = state
                memory.execute('INSERT INTO process_network_status(session_id, sampled_at, state) VALUES (?, ?, ?)',
                               (sid, at, state))
            elif typ == 'process_network':
                process = event.get('process')
                received, sent = event.get('received_bytes'), event.get('sent_bytes')
                if (process_network_states.get(session_key) != 'enabled'
                        or not isinstance(process, str) or not process or len(process) > 128
                        or any(ord(char) < 32 for char in process)
                        or not all(isinstance(value, int) and not isinstance(value, bool)
                                   and 0 <= value <= 2**63 - 1 for value in (received, sent))
                        or (received == 0 and sent == 0)):
                    raise ValueError('invalid process network observation')
                memory.execute('INSERT INTO process_network_samples(session_id, sampled_at, process_name, received_bytes, sent_bytes) VALUES (?, ?, ?, ?, ?)',
                               (sid, at, process, received, sent))
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
