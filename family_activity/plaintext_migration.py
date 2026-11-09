"""Explicit conversion of an old plaintext activity database to encrypted events.

The source is opened read-only and never deleted. The encrypted output is
published with an exclusive hard link only after conversion succeeds.
"""
from datetime import datetime, timedelta, timezone
import heapq
import os
from pathlib import Path
import re
import sqlite3
import tempfile

from . import browser_channel, encrypted_store, parent_settings, public_key_file
from .encrypted_agent_store import EncryptedAgentStore


SCHEMA = {
    'sessions': {'id', 'started_at', 'heartbeat_at', 'stopped_at'},
    'foreground_samples': {'id', 'session_id', 'sampled_at', 'app_name', 'bundle_id'},
    'network_intervals': {'id', 'session_id', 'from_at', 'to_at', 'interface', 'received_bytes', 'sent_bytes'},
    'website_samples': {'id', 'session_id', 'sampled_at', 'domain'},
    'network_settings': {'id', 'session_id', 'sampled_at', 'dns_observed', 'proxy_indicator', 'vpn_indicator'},
    'network_changes': {'id', 'session_id', 'sampled_at', 'identifier'},
    'gaps': {'id', 'session_id', 'from_at', 'to_at'},
}
OPTIONAL_EMPTY_SCHEMA = {
    # Added to the modern local projection after the original plaintext schema.
    # The agent writes these only to encrypted storage; permit empty projection
    # tables from newer stores while refusing to silently discard any rows.
    'process_network_samples': {'id', 'session_id', 'sampled_at', 'process_name', 'received_bytes', 'sent_bytes'},
    'process_network_status': {'id', 'session_id', 'sampled_at', 'state'},
}
SESSION_OPTIONAL_COLUMNS = {'device_id', 'restarted_after_unclean_exit'}
MAX_COUNTER = 2**63 - 1


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError('plaintext database contains an invalid timestamp')
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError('plaintext database contains an invalid timestamp') from None
    if parsed.utcoffset() != timedelta(0) or parsed.isoformat(timespec='microseconds') != value:
        raise ValueError('timestamps must use the original UTC microsecond format')
    return parsed


def _session_id(value, known):
    if not isinstance(value, int) or value not in known:
        raise ValueError('plaintext database contains an unknown session reference')
    return str(value)


def _counter(value):
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= MAX_COUNTER:
        raise ValueError('plaintext database contains an invalid byte counter')
    return value


def _secure_event_streams(db, sessions):
    """Create bounded-memory, already-sorted event streams for heap merging."""
    def stream(query, event_type, priority, convert):
        for row in db.execute(query):
            timestamp = _timestamp(row[0])
            sid = _session_id(row[1], sessions)
            row_id = row[2]
            if not isinstance(row_id, int):
                raise ValueError('plaintext database contains an invalid row id')
            yield (timestamp, int(sid), priority, row_id, event_type, sid, convert(row[3:]))

    streams = [
        stream('SELECT started_at,id,id FROM sessions ORDER BY started_at,id', 'start', 0,
               lambda fields: {}),
        stream('SELECT sampled_at,session_id,id,app_name,bundle_id FROM foreground_samples ORDER BY sampled_at,session_id,id',
               'foreground', 1, lambda f: {'application': None if f == (None, None) else _application(f)}),
        stream('SELECT sampled_at,session_id,id,domain FROM website_samples ORDER BY sampled_at,session_id,id',
               'website', 2, lambda f: {'domain': browser_channel.validate({'domain': f[0]})}),
        stream('SELECT to_at,session_id,id,from_at,to_at,interface,received_bytes,sent_bytes FROM network_intervals ORDER BY to_at,session_id,id',
               'network', 3, lambda f: {'intervals': [_network_interval(f)]}),
        stream('SELECT sampled_at,session_id,id,dns_observed,proxy_indicator,vpn_indicator FROM network_settings ORDER BY sampled_at,session_id,id',
               'network_settings', 4, _settings),
        stream('SELECT sampled_at,session_id,id,identifier FROM network_changes ORDER BY sampled_at,session_id,id',
               'network_identity', 5, lambda f: _identifier(f[0])),
        stream('SELECT CASE WHEN s.stopped_at IS NOT NULL AND g.to_at>s.stopped_at THEN g.from_at ELSE g.to_at END, '
               'g.session_id,g.id,g.from_at,g.to_at FROM gaps AS g JOIN sessions AS s ON s.id=g.session_id '
               'ORDER BY 1,g.session_id,g.id',
               'gap', 6, _gap),
        stream('SELECT heartbeat_at,id,id FROM sessions ORDER BY heartbeat_at,id', 'heartbeat', 7,
               lambda fields: {}),
        stream('SELECT stopped_at,id,id FROM sessions WHERE stopped_at IS NOT NULL ORDER BY stopped_at,id',
               'stop', 8, lambda fields: {}),
    ]
    session_columns = {row[1] for row in db.execute('PRAGMA table_info(sessions)')}
    if 'restarted_after_unclean_exit' in session_columns:
        streams.insert(1, stream(
            'SELECT started_at,id,id FROM sessions WHERE restarted_after_unclean_exit=1 ORDER BY started_at,id',
            'restart_marker', 1, lambda fields: {}))
    return streams


def _application(fields):
    if not all(isinstance(value, str) for value in fields):
        raise ValueError('plaintext database contains an invalid application observation')
    return list(fields)


def _network_interval(fields):
    start, finish, interface, received, sent = fields
    start_at, finish_at = _timestamp(start), _timestamp(finish)
    if not isinstance(interface, str):
        raise ValueError('plaintext database contains an invalid interface name')
    if start_at >= finish_at:
        raise ValueError('plaintext database contains an invalid network interval')
    return [start, finish, interface, _counter(received), _counter(sent)]


def _settings(fields):
    values = []
    for value in fields:
        if value is None:
            values.append(None)
        elif isinstance(value, int) and not isinstance(value, bool) and value in (0, 1):
            values.append(bool(value))
        else:
            raise ValueError('plaintext database contains an invalid network setting')
    return dict(zip(('dns_observed', 'proxy_indicator', 'vpn_indicator'), values))


def _identifier(value):
    if value is not None and (not isinstance(value, str) or re.fullmatch(r'[0-9a-f]{64}', value) is None):
        raise ValueError('plaintext database contains an invalid network identifier')
    return {'identifier': value}


def _gap(fields):
    start, finish = fields
    if _timestamp(finish) <= _timestamp(start):
        raise ValueError('plaintext database contains an invalid observation gap')
    return {'from_at': start, 'to_at': finish}


def encrypt_legacy_database(source_path, public_key_path, output_path, retention_days=30):
    """Encrypt a plaintext prototype DB into a new file; preserve the source.

    The destination must not exist. Expiry is calculated from each original
    event timestamp, so conversion does not extend the source's effective age.
    """
    parent_settings.validate_retention_days(retention_days)
    source_path = Path(source_path).expanduser()
    output_path = Path(output_path).expanduser()
    public_key_path = Path(public_key_path).expanduser()
    for path, label in ((source_path, 'source'), (public_key_path, 'public-key')):
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'{label} path must be a regular file, not a symbolic link')
    if source_path.resolve() == output_path.resolve():
        raise ValueError('encrypted output must be a different file from the plaintext source')
    if output_path.is_symlink() or output_path.exists():
        raise FileExistsError('encrypted output already exists; choose a new path')
    if not output_path.parent.is_dir():
        raise ValueError('encrypted output directory must already exist')
    public = public_key_file.decode(public_key_path.read_bytes(), allow_legacy=True)
    source_uri = source_path.resolve().as_uri() + '?mode=ro'
    source = sqlite3.connect(source_uri, uri=True, timeout=5)
    temp_path = None
    writer = None
    try:
        source.execute('PRAGMA query_only=ON')
        source.execute('PRAGMA temp_store=MEMORY')
        source.execute('BEGIN')
        if source.execute('PRAGMA integrity_check').fetchone() != ('ok',):
            raise ValueError('plaintext source database failed its integrity check')
        tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not set(SCHEMA).issubset(tables) or not tables.issubset(set(SCHEMA) | set(OPTIONAL_EMPTY_SCHEMA)):
            raise ValueError('source is not a supported plaintext activity database')
        extra_objects = source.execute("SELECT 1 FROM sqlite_master WHERE type IN ('view','trigger') LIMIT 1").fetchone()
        if extra_objects is not None:
            raise ValueError('source activity database schema is unsupported')
        for name, expected in {**SCHEMA, **OPTIONAL_EMPTY_SCHEMA}.items():
            if name not in tables:
                continue
            columns = {row[1] for row in source.execute(f'PRAGMA table_info("{name}")')}
            accepted = tuple(expected | extensions for extensions in (
                set(), {'device_id'}, {'restarted_after_unclean_exit'}, SESSION_OPTIONAL_COLUMNS
            )) if name == 'sessions' else (expected,)
            if columns not in accepted:
                raise ValueError('source activity database schema is unsupported')
            if name in OPTIONAL_EMPTY_SCHEMA and source.execute(f'SELECT 1 FROM "{name}" LIMIT 1').fetchone() is not None:
                raise ValueError('source contains newer process network records that this migration cannot preserve')
        if 'restarted_after_unclean_exit' in {row[1] for row in source.execute('PRAGMA table_info(sessions)')}:
            invalid_restart = source.execute(
                'SELECT 1 FROM sessions WHERE restarted_after_unclean_exit NOT IN (0,1) LIMIT 1').fetchone()
            if invalid_restart is not None:
                raise ValueError('source contains an invalid restart marker')
        if source.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise ValueError('plaintext source contains broken session references')
        gap_rows = source.execute('SELECT count(*) FROM gaps').fetchone()[0]
        joined_gaps = source.execute('SELECT count(*) FROM gaps AS g JOIN sessions AS s ON s.id=g.session_id').fetchone()[0]
        if gap_rows != joined_gaps:
            raise ValueError('plaintext source contains gaps with missing sessions')
        sessions = {}
        for sid, start, heartbeat, stopped in source.execute('SELECT id,started_at,heartbeat_at,stopped_at FROM sessions'):
            if not isinstance(sid, int) or sid in sessions:
                raise ValueError('source contains an invalid session id')
            start_at, heartbeat_at = _timestamp(start), _timestamp(heartbeat)
            if heartbeat_at < start_at:
                raise ValueError('source contains an invalid session boundary')
            stop_at = _timestamp(stopped) if stopped is not None else None
            if stop_at is not None and stop_at < heartbeat_at:
                raise ValueError('source contains an invalid session boundary')
            sessions[sid] = (start_at, heartbeat_at, stop_at)
        if not sessions:
            raise ValueError('source contains no activity sessions')

        descriptor, temp_name = tempfile.mkstemp(prefix='.family-activity-encrypted-', dir=output_path.parent)
        os.close(descriptor)
        temp_path = Path(temp_name)
        writer = EncryptedAgentStore(temp_path, public, retention_days)
        inserted = 0
        streams = _secure_event_streams(source, sessions)
        writer.db.execute('BEGIN')
        for timestamp, _, _, _, event_type, sid, fields in heapq.merge(*streams, key=lambda item: item[:4]):
            if event_type == 'network':
                start_at = fields['intervals'][0][0]
                if _timestamp(start_at) >= timestamp:
                    raise ValueError('source contains an invalid network interval')
            event = {'type': event_type, 'session': sid,
                     'at': timestamp.isoformat(timespec='microseconds'), **fields}
            expiry = (timestamp.date() + timedelta(days=retention_days + 1)).isoformat()
            ciphertext = encrypted_store.seal_event(public, event)
            writer.db.execute('INSERT INTO encrypted_events(expires_on,ciphertext) VALUES (?,?)',
                              (expiry, ciphertext))
            inserted += 1
        writer.db.commit()
        writer.prune(datetime.now(timezone.utc))
        retained = writer.db.execute('SELECT count(*) FROM encrypted_events').fetchone()[0]
        writer.close()
        writer = None
        # Windows requires a writable handle for fsync; the completed database
        # is closed above, so this cannot change its contents.
        with temp_path.open('rb+') as stream:
            os.fsync(stream.fileno())
        os.link(temp_path, output_path)
        temp_path.unlink()
        temp_path = None
        try:
            directory_fd = os.open(output_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
        return {'output': str(output_path), 'inserted_events': inserted,
                'retained_events': retained, 'source_sessions': len(sessions)}
    finally:
        source.close()
        if writer is not None:
            writer.close()
        if temp_path is not None:
            for candidate in (temp_path, Path(str(temp_path) + '-wal'), Path(str(temp_path) + '-shm'),
                              Path(str(temp_path) + '-journal')):
                try:
                    candidate.unlink()
                except FileNotFoundError:
                    pass
