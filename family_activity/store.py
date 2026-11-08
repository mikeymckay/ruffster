"""Session and heartbeat storage; gaps are uncertain intervals, not diagnoses."""
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def connect(path):
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Do not change permissions on an existing user-supplied file.
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        pass
    else:
        os.close(fd)
    db = sqlite3.connect(path, timeout=5)
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'encrypted_events' in tables or 'sealed_events' in tables:
        db.close()
        raise ValueError("encrypted database cannot be opened as a plaintext activity database")
    db.execute("PRAGMA busy_timeout=5000")
    db.execute("PRAGMA secure_delete=ON")
    initialize(db)
    return db


def initialize(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
          id INTEGER PRIMARY KEY, started_at TEXT NOT NULL,
          heartbeat_at TEXT NOT NULL, stopped_at TEXT
        );
        CREATE TABLE IF NOT EXISTS foreground_samples (
          id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, sampled_at TEXT NOT NULL,
          app_name TEXT, bundle_id TEXT,
          FOREIGN KEY(session_id) REFERENCES sessions(id)
        );
        CREATE TABLE IF NOT EXISTS network_intervals (
          id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL,
          from_at TEXT NOT NULL, to_at TEXT NOT NULL, interface TEXT NOT NULL,
          received_bytes INTEGER NOT NULL, sent_bytes INTEGER NOT NULL,
          FOREIGN KEY(session_id) REFERENCES sessions(id)
        );
        CREATE TABLE IF NOT EXISTS process_network_samples (
          id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, sampled_at TEXT NOT NULL,
          process_name TEXT NOT NULL, received_bytes INTEGER NOT NULL, sent_bytes INTEGER NOT NULL,
          FOREIGN KEY(session_id) REFERENCES sessions(id)
        );
        CREATE TABLE IF NOT EXISTS process_network_status (
          id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, sampled_at TEXT NOT NULL,
          state TEXT NOT NULL, FOREIGN KEY(session_id) REFERENCES sessions(id)
        );
        CREATE TABLE IF NOT EXISTS website_samples (
          id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, sampled_at TEXT NOT NULL,
          domain TEXT, FOREIGN KEY(session_id) REFERENCES sessions(id)
        );
        CREATE TABLE IF NOT EXISTS network_settings (
          id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, sampled_at TEXT NOT NULL,
          dns_observed INTEGER, proxy_indicator INTEGER, vpn_indicator INTEGER,
          FOREIGN KEY(session_id) REFERENCES sessions(id)
        );
        CREATE TABLE IF NOT EXISTS network_changes (
          id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, sampled_at TEXT NOT NULL,
          identifier TEXT, FOREIGN KEY(session_id) REFERENCES sessions(id)
        );
        CREATE TABLE IF NOT EXISTS gaps (
          id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL,
          from_at TEXT NOT NULL, to_at TEXT NOT NULL,
          FOREIGN KEY(session_id) REFERENCES sessions(id)
        );
    """)


def start(db, timestamp=None):
    timestamp = timestamp or now()
    with db:
        for sid, heartbeat in db.execute("SELECT id, heartbeat_at FROM sessions WHERE stopped_at IS NULL").fetchall():
            # A backward clock makes the interval unknowable; don't invent a negative gap.
            if timestamp >= heartbeat:
                db.execute("INSERT INTO gaps(session_id, from_at, to_at) VALUES (?, ?, ?)", (sid, heartbeat, timestamp))
            db.execute("UPDATE sessions SET stopped_at = ? WHERE id = ?", (heartbeat, sid))
        return db.execute("INSERT INTO sessions(started_at, heartbeat_at) VALUES (?, ?)", (timestamp, timestamp)).lastrowid


def heartbeat(db, sid, timestamp=None):
    with db:
        db.execute("UPDATE sessions SET heartbeat_at = ? WHERE id = ? AND stopped_at IS NULL", (timestamp or now(), sid))


def stop(db, sid, timestamp=None):
    timestamp = timestamp or now()
    with db:
        db.execute("UPDATE sessions SET heartbeat_at = ?, stopped_at = ? WHERE id = ? AND stopped_at IS NULL", (timestamp, timestamp, sid))


def record_gap(db, sid, from_at, to_at):
    """Record a known unobserved interval without assigning a cause."""
    try:
        start = datetime.fromisoformat(from_at)
        end = datetime.fromisoformat(to_at)
    except (TypeError, ValueError):
        raise ValueError('gap boundaries must be ISO timestamps') from None
    if start.utcoffset() is None or end.utcoffset() is None or end <= start:
        raise ValueError('gap boundaries must be ordered timezone-aware timestamps')
    with db:
        active = db.execute('SELECT 1 FROM sessions WHERE id = ? AND stopped_at IS NULL', (sid,)).fetchone()
        if active is None:
            raise ValueError('gap session is not active')
        db.execute('INSERT INTO gaps(session_id, from_at, to_at) VALUES (?, ?, ?)', (sid, from_at, to_at))


def record_foreground(db, sid, application, timestamp=None):
    """Record one observation; null fields explicitly represent unknown."""
    name, bundle_id = application if application is not None else (None, None)
    with db:
        db.execute("INSERT INTO foreground_samples(session_id, sampled_at, app_name, bundle_id) VALUES (?, ?, ?, ?)",
                   (sid, timestamp or now(), name, bundle_id))


def prune(db, retention_days, reference=None):
    """Delete expired records without deleting an open session or a recent gap."""
    if retention_days < 1:
        raise ValueError("retention_days must be at least one")
    reference = reference or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        raise ValueError("reference must be timezone-aware")
    cutoff = (reference.astimezone(timezone.utc) - timedelta(days=retention_days)).isoformat(timespec="microseconds")
    with db:
        db.execute("DELETE FROM foreground_samples WHERE julianday(sampled_at) < julianday(?)", (cutoff,))
        db.execute("DELETE FROM network_intervals WHERE julianday(to_at) < julianday(?)", (cutoff,))
        db.execute("DELETE FROM process_network_samples WHERE julianday(sampled_at) < julianday(?)", (cutoff,))
        db.execute("DELETE FROM process_network_status WHERE julianday(sampled_at) < julianday(?)", (cutoff,))
        db.execute("DELETE FROM gaps WHERE julianday(to_at) < julianday(?)", (cutoff,))
        db.execute("""DELETE FROM sessions WHERE stopped_at IS NOT NULL
                      AND julianday(stopped_at) < julianday(?)
                      AND NOT EXISTS (SELECT 1 FROM gaps WHERE gaps.session_id = sessions.id)
                      AND NOT EXISTS (SELECT 1 FROM foreground_samples WHERE foreground_samples.session_id = sessions.id)
                      AND NOT EXISTS (SELECT 1 FROM network_intervals WHERE network_intervals.session_id = sessions.id)
                      AND NOT EXISTS (SELECT 1 FROM process_network_samples WHERE process_network_samples.session_id = sessions.id)
                      AND NOT EXISTS (SELECT 1 FROM process_network_status WHERE process_network_status.session_id = sessions.id)""", (cutoff,))


def record_network(db, sid, intervals):
    with db:
        db.executemany("INSERT INTO network_intervals(session_id, from_at, to_at, interface, received_bytes, sent_bytes) VALUES (?, ?, ?, ?, ?, ?)",
                       ((sid, *interval) for interval in intervals))
