"""Experimental local parent setup and report UI; no cloud or remote listener."""
from datetime import date, datetime, timedelta, timezone
import base64
import hashlib
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
import hmac
import json
import os
from pathlib import Path
import secrets
import signal
import sqlite3
from socketserver import TCPServer
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlsplit
import webbrowser
from zoneinfo import ZoneInfo
from nacl.public import PrivateKey
from . import device_labels, encrypted_store, encrypted_view, key_vault, network_labels, parent_settings, public_key_file, reports, school_schedule, website_categories
from .encrypted_agent_store import EncryptedAgentStore, EXPIRY_VERSION, LEGACY_EXPIRY_VERSION
from .encrypted_store import CIPHERTEXT_SIZES
from .limits import MAX_SNAPSHOT_BYTES

MAX_UPLOAD = MAX_SNAPSHOT_BYTES
KEY_IDLE_TIMEOUT_SECONDS = 15 * 60
ASSETS = Path(__file__).with_name('parent_assets')


class ParentServer(HTTPServer):
    def server_bind(self):
        TCPServer.server_bind(self)
        self.server_name = '127.0.0.1'
        self.server_port = self.socket.getsockname()[1]

    def __init__(self, folder, port=0):
        self.folder = Path(folder).expanduser()
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name == 'posix' and (self.folder.stat().st_uid != os.getuid() or self.folder.stat().st_mode & 0o077):
            raise ValueError('parent data directory must be private to this account')
        self.token = secrets.token_urlsafe(32)
        self.login_consumed = False
        self._private_key = None
        self._private_key_last_used = None
        self._key_share_lock = threading.Lock()
        self._key_share_server = None
        self._key_share_thread = None
        self.settings = self.folder / 'parent-settings.json'
        self.retention_days = parent_settings.load_retention(self.settings)
        self.backup_confirmed = parent_settings.load_backup_confirmation(self.settings)
        self.backup_downloaded = False
        super().__init__(('127.0.0.1', port), Handler)

    @property
    def vault(self): return self.folder / 'parent.vault'

    @property
    def data(self): return self.folder / 'report.sqlite3'

    @property
    def labels(self): return self.folder / 'network-labels.sealed'

    @property
    def schedule(self): return self.folder / 'school-schedule.sealed'

    def _expire_private_key(self):
        if (self._private_key is not None and self._private_key_last_used is not None and
                time.monotonic() - self._private_key_last_used >= KEY_IDLE_TIMEOUT_SECONDS):
            self._private_key = None
            self._private_key_last_used = None
            self.stop_public_key_share()

    @property
    def key_unlocked(self):
        self._expire_private_key()
        return self._private_key is not None

    @property
    def private_key(self):
        self._expire_private_key()
        if self._private_key is not None:
            self._private_key_last_used = time.monotonic()
        return self._private_key

    @private_key.setter
    def private_key(self, value):
        self._private_key = value
        self._private_key_last_used = time.monotonic() if value is not None else None

    @property
    def url(self): return f'http://127.0.0.1:{self.server_port}/#{self.token}'

    def start_public_key_share(self):
        from .local_share import PublicKeyShareServer, local_ipv4_address
        private_key = self.private_key
        if private_key is None:
            raise ValueError('unlock the parent key first')
        with self._key_share_lock:
            current = self._key_share_server
            if current is not None and not current.used and time.monotonic() < current.deadline:
                return current.short_code
        # A one-use share may have been consumed while its serving thread is
        # still closing the UDP discovery socket. Join that thread before
        # binding a replacement; Windows in particular may reject the new bind
        # while the previous listener is still unwinding.
        if current is not None:
            self.stop_public_key_share()
        with self._key_share_lock:
            current = self._key_share_server
            if current is not None and not current.used and time.monotonic() < current.deadline:
                return current.short_code
            if current is not None:
                raise RuntimeError('the previous nearby connection is still closing; try again shortly')
            host = local_ipv4_address()
            transfer = PublicKeyShareServer(private_key.public_key, host, lifetime=300)
            self._key_share_server = transfer

            def serve():
                try:
                    transfer.serve_once()
                finally:
                    transfer.server_close()
                    with self._key_share_lock:
                        if self._key_share_server is transfer:
                            self._key_share_server = None
                            self._key_share_thread = None

            thread = threading.Thread(target=serve, daemon=True, name='family-public-key-share')
            self._key_share_thread = thread
            thread.start()
            return transfer.short_code

    def stop_public_key_share(self):
        with self._key_share_lock:
            transfer, thread = self._key_share_server, self._key_share_thread
            if transfer is None:
                return False
            transfer.cancel()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)
        return True

    def server_close(self):
        self.stop_public_key_share()
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Never log URLs, request bodies, or report data.

    def _headers(self, status=200, content_type='application/json; charset=utf-8', extra=(), content_length=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        if content_length is not None:
            self.send_header('Content-Length', str(content_length))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        for key, value in extra:
            self.send_header(key, value)
        self.end_headers()

    def _json(self, value, status=200, extra=()):
        data = json.dumps(value, ensure_ascii=False).encode('utf-8')
        self._headers(status, extra=extra, content_length=len(data))
        self.wfile.write(data)

    def _valid_host(self):
        return self.headers.get('Host', '').lower() == f'127.0.0.1:{self.server.server_port}'

    def _valid_origin(self):
        return self.headers.get('Origin', '') == f'http://127.0.0.1:{self.server.server_port}'

    def _valid_api_read_context(self):
        """Reject browser API reads initiated by other loopback web origins."""
        origin = self.headers.get('Origin')
        if origin is not None and not self._valid_origin():
            return False
        fetch_site = self.headers.get('Sec-Fetch-Site')
        return fetch_site is None or fetch_site in {'same-origin', 'none'}

    def _authorized(self):
        try:
            cookie = SimpleCookie(self.headers.get('Cookie', ''))
            value = cookie['family_session'].value
            return hmac.compare_digest(value, self.server.token)
        except (KeyError, ValueError):
            return False

    def _body(self, limit=4096):
        if self.headers.get('Transfer-Encoding'):
            raise ValueError('unsupported request')
        length = int(self.headers.get('Content-Length', '-1'))
        if length < 0 or length > limit:
            raise ValueError('invalid request length')
        data = self.rfile.read(length)
        if len(data) != length:
            raise ValueError('incomplete request')
        return data

    def do_GET(self):
        if not self._valid_host():
            self._json({'error': 'Forbidden'}, 403); return
        request_path = urlsplit(self.path).path
        assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                  '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                  '/app.css': ('app.css', 'text/css; charset=utf-8'),
                  '/ruffster-mascot.webp': ('ruffster-mascot.webp', 'image/webp')}
        if request_path in assets and not urlsplit(self.path).query:
            file, kind = assets[request_path]
            self._headers(content_type=kind); self.wfile.write((ASSETS / file).read_bytes()); return
        if self.path.startswith('/api/') and not self._valid_api_read_context():
            self._json({'error': 'Forbidden'}, 403); return
        if not self._authorized():
            self._json({'error': 'Open the app from its local launcher.'}, 403); return
        if self.path == '/api/status':
            self._json({'has_key': self.server.vault.is_file(), 'unlocked': self.server.key_unlocked,
                        'has_report': self.server.data.is_file(),
                        'backup_confirmed': self.server.backup_confirmed}); return
        if self.path == '/api/settings':
            if self.server.private_key is None:
                self._json({'error': 'Unlock the parent key first.'}, 403); return
            self._json({'retention_days': self.server.retention_days}); return
        if self.path in ('/api/public', '/api/backup'):
            if self.server.private_key is None:
                self._json({'error': 'Unlock the parent key first.'}, 403); return
            if self.path.endswith('public'):
                if not self.server.backup_confirmed:
                    self._json({'error': 'Save and confirm the encrypted parent key backup before setting up a child computer.'}, 403); return
                content = public_key_file.encode(self.server.private_key.public_key)
            else:
                content = self.server.vault.read_bytes()
                self.server.backup_downloaded = True
            name = 'ruffster-public.key' if self.path.endswith('public') else 'ruffster-parent-backup.vault'
            self._headers(content_type='application/octet-stream', extra=(('Content-Disposition', f'attachment; filename="{name}"'),))
            self.wfile.write(content); return
        if self.path == '/api/schedule':
            if self.server.private_key is None:
                self._json({'error': 'Unlock the parent key first.'}, 403); return
            try:
                self._json({'schedule': school_schedule.load(self.server.schedule, self.server.private_key)})
            except Exception:
                self._json({'error': 'The school schedule could not be opened.'}, 400)
            return
        if request_path == '/api/report':
            if self.server.private_key is None or not self.server.data.is_file():
                self._json({'error': 'Unlock the key and import a report first.'}, 403); return
            try:
                _prune_report_file(self.server.data, self.server.private_key, self.server.retention_days)
                query = parse_qs(urlsplit(self.path).query, strict_parsing=True, keep_blank_values=True)
                if set(query) - {'device'} or any(len(values) != 1 for values in query.values()):
                    raise ValueError('invalid report selection')
                selected_device = query.get('device', [None])[0]
                self._json(_report(self.server.data, self.server.private_key, self.server.labels,
                                   self.server.schedule, selected_device))
            except Exception:
                self._json({'error': 'The report could not be opened with this key.'}, 400)
            return
        if self.path == '/api/report-backup':
            if self.server.private_key is None or not self.server.data.is_file():
                self._json({'error': 'Unlock the key and import a report first.'}, 403); return
            try:
                from .local_share import encrypted_snapshot
                content = encrypted_snapshot(self.server.data)
                self._headers(content_type='application/octet-stream', extra=(
                    ('Content-Disposition', 'attachment; filename="ruffster-report.sqlite3"'),
                    ('Cache-Control', 'no-store')))
                self.wfile.write(content)
            except Exception:
                self._json({'error': 'The encrypted report backup could not be created.'}, 400)
            return
        self._json({'error': 'Not found'}, 404)

    def do_POST(self):
        if not self._valid_host() or not self._valid_origin():
            self._json({'error': 'Forbidden'}, 403); return
        self.connection.settimeout(15)
        if self.path == '/api/login':
            try:
                value = json.loads(self._body()).get('token', '')
                valid = isinstance(value, str) and hmac.compare_digest(value, self.server.token)
            except (ValueError, TypeError):
                valid = False
            if not valid or self.server.login_consumed:
                self._json({'error': 'Session not available.'}, 403); return
            self.server.login_consumed = True
            cookie = f'family_session={self.server.token}; Path=/; HttpOnly; SameSite=Strict'
            self._json({'ok': True}, extra=(('Set-Cookie', cookie),)); return
        if not self._authorized():
            self._json({'error': 'Open the app from its local launcher.'}, 403); return
        if self.path == '/api/public-key-share':
            if self.server.private_key is None:
                self._json({'error': 'Unlock the parent key first.'}, 403); return
            if not self.server.backup_confirmed:
                self._json({'error': 'Save and confirm the encrypted parent key backup before setting up a child computer.'}, 403); return
            try:
                code = self.server.start_public_key_share()
                transfer = self.server._key_share_server
                remaining = max(0, int(transfer.deadline - time.monotonic())) if transfer else 0
                self._json({'code': code, 'expires_in': remaining})
            except Exception:
                self._json({'error': 'Could not show the digits. Check that both computers are on the same Wi-Fi, then try again.'}, 400)
            return
        if self.path == '/api/public-key-share/stop':
            self.server.stop_public_key_share()
            self._json({'stopped': True}); return
        if self.path == '/api/restore-key':
            try:
                body = json.loads(self._body())
                encoded, password = body.get('backup'), body.get('passphrase')
                if not isinstance(encoded, str) or not isinstance(password, str):
                    raise ValueError('invalid key backup')
                backup = base64.b64decode(encoded, validate=True)
                key = key_vault.unlock(backup, password)
                if self.server.vault.exists():
                    raise FileExistsError('a parent key already exists on this device')
                parent_settings.save_backup_confirmation(self.server.settings, False)
                key_vault.create_new(self.server.vault, backup)
                self.server.private_key = key
                self.server.backup_confirmed = False
                self.server.backup_downloaded = False
                self._json({'ok': True})
            except FileExistsError:
                self._json({'error': 'A parent key already exists on this device. Unlock it instead; existing keys are never replaced.'}, 409)
            except Exception:
                self._json({'error': 'Could not restore that backup. Check the recovery copy and parent access PIN (or the older passphrase used for it).'}, 400)
            return
        if self.path == '/api/change-pin':
            if self.server.private_key is None:
                self._json({'error': 'Unlock parent access first.'}, 403); return
            try:
                body = json.loads(self._body())
                if not isinstance(body, dict):
                    raise ValueError('invalid request')
                current_pin = body.get('current_pin')
                new_pin = body.get('new_pin')
                confirm_pin = body.get('confirm_pin')
                if not all(isinstance(value, str) for value in (current_pin, new_pin, confirm_pin)):
                    raise ValueError('invalid request')
                if new_pin != confirm_pin:
                    self._json({'error': 'The new PINs do not match.'}, 400); return
                if new_pin == current_pin:
                    self._json({'error': 'Choose a different six-digit PIN.'}, 400); return
                current_key = key_vault.unlock(self.server.vault.read_bytes(), current_pin)
                if not hmac.compare_digest(bytes(current_key), bytes(self.server.private_key)):
                    raise ValueError('current PIN does not match the unlocked parent key')
                backup = key_vault.encrypt_private_key(self.server.private_key, new_pin)
                self.server.stop_public_key_share()
                parent_settings.save_backup_confirmation(self.server.settings, False)
                self.server.backup_confirmed = False
                self.server.backup_downloaded = False
                key_vault.replace_existing_private(self.server.vault, backup)
                self._json({'ok': True, 'backup_confirmed': False})
            except Exception:
                self._json({'error': 'Could not change the PIN. Check your current PIN and choose a new six-digit PIN.'}, 400)
            return
        if self.path in ('/api/create', '/api/unlock'):
            try:
                body = json.loads(self._body())
                password = body['passphrase']
                if not isinstance(password, str): raise ValueError('invalid passphrase')
                if self.path == '/api/create':
                    if password != body.get('confirm'): raise ValueError('PINs do not match')
                    if self.server.vault.exists():
                        raise FileExistsError('a parent key already exists')
                    key = PrivateKey.generate()
                    backup = key_vault.encrypt_private_key(key, password)
                    parent_settings.save_backup_confirmation(self.server.settings, False)
                    key_vault.create_new(self.server.vault, backup)
                    self.server.backup_confirmed = False
                    self.server.backup_downloaded = False
                else:
                    key = key_vault.unlock(self.server.vault.read_bytes(), password)
                self.server.private_key = key
                self._json({'ok': True})
            except FileExistsError:
                self._json({'error': 'A parent key already exists. Unlock it instead.'}, 409)
            except Exception:
                self._json({'error': 'Could not set up or unlock parent access. New access uses a six-digit PIN; for an older setup, use its original passphrase.'}, 400)
            return
        if self.path == '/api/confirm-key-backup':
            if self.server.private_key is None:
                self._json({'error': 'Unlock the parent key first.'}, 403); return
            try:
                body = json.loads(self._body())
                if not isinstance(body, dict) or body.get('confirmed') is not True or not self.server.backup_downloaded:
                    raise ValueError('confirmation is required')
                parent_settings.save_backup_confirmation(self.server.settings, True)
                self.server.backup_confirmed = True
                self.server.backup_downloaded = False
                self._json({'backup_confirmed': True})
            except Exception:
                self._json({'error': 'Confirm that you saved the encrypted parent key backup.'}, 400)
            return
        if self.path == '/api/lock':
            self.server.stop_public_key_share()
            self.server.private_key = None
            self._json({'ok': True}); return
        if self.path == '/api/delete-report':
            if self.server.private_key is None:
                self._json({'error': 'Unlock the parent key first.'}, 403); return
            paths = [self.server.data] + [Path(str(self.server.data) + suffix)
                                          for suffix in ('-wal', '-shm', '-journal')]
            try:
                for path in paths:
                    if path.is_symlink():
                        raise ValueError('report path must not be a symbolic link')
                for path in paths:
                    path.unlink(missing_ok=True)
                self._json({'deleted': True})
            except OSError:
                self._json({'error': 'The local report could not be deleted.'}, 400)
            except ValueError:
                self._json({'error': 'The report path is not a regular local file.'}, 400)
            return
        if self.path == '/api/delete-device':
            if self.server.private_key is None:
                self._json({'error': 'Unlock the parent key first.'}, 403); return
            try:
                body = json.loads(self._body())
                removed = _remove_device_records(
                    self.server.data, self.server.private_key, self.server.retention_days,
                    body.get('device_id'))
                self._json({'deleted': True, 'events_removed': removed})
            except Exception:
                self._json({'error': 'That computer could not be removed from this parent report.'}, 400)
            return
        if self.path == '/api/schedule':
            if self.server.private_key is None:
                self._json({'error': 'Unlock the parent key first.'}, 403); return
            try:
                body = json.loads(self._body())
                self._json({'schedule': school_schedule.save(self.server.schedule, self.server.private_key, body)})
            except Exception:
                self._json({'error': 'Choose valid weekdays, a time zone, and an end time after the start time.'}, 400)
            return
        if self.path == '/api/retention':
            if self.server.private_key is None:
                self._json({'error': 'Unlock the parent key first.'}, 403); return
            try:
                body = json.loads(self._body())
                days = parent_settings.validate_retention_days(body.get('retention_days'))
                if self.server.data.is_file():
                    _prune_report_file(self.server.data, self.server.private_key, days)
                parent_settings.save_retention(self.server.settings, days)
                self.server.retention_days = days
                self._json({'retention_days': days})
            except Exception:
                self._json({'error': 'Choose 7, 30, 90, 180, or 365 days.'}, 400)
            return
        if self.path == '/api/network-label':
            if self.server.private_key is None:
                self._json({'error': 'Unlock the parent key first.'}, 403); return
            try:
                body = json.loads(self._body())
                network_labels.set_label(self.server.labels, self.server.private_key, body['identifier'], body['label'])
                self._json({'ok': True})
            except Exception:
                self._json({'error': 'The network label could not be saved.'}, 400)
            return
        if self.path == '/api/device-label':
            if self.server.private_key is None:
                self._json({'error': 'Unlock the parent key first.'}, 403); return
            try:
                body = json.loads(self._body())
                if not self.server.data.is_file():
                    raise ValueError('no computer report is available')
                projection, _ = encrypted_view.open_projection(self.server.data, self.server.private_key)
                try:
                    known_devices = {row[0] for row in projection.execute(
                        'SELECT DISTINCT device_id FROM sessions')}
                finally:
                    projection.close()
                if body.get('device_id') not in known_devices:
                    raise ValueError('computer is not in this report')
                _prune_report_file(self.server.data, self.server.private_key, self.server.retention_days)
                device_labels.set_label(self.server.data, self.server.private_key,
                                        body['device_id'], body['label'], self.server.retention_days)
                self._json({'ok': True})
            except Exception:
                self._json({'error': 'The computer name could not be saved.'}, 400)
            return
        if self.path == '/api/sync':
            if self.server.private_key is None:
                self._json({'error': 'Unlock the parent key first.'}, 403); return
            try:
                from .local_share import fetch
                code = json.loads(self._body())['code']
                data = fetch(code)
                _install_report(self.server, data)
                self._json({'ok': True})
            except Exception:
                self._json({'error': 'Could not receive the report. Check the two digits and Wi-Fi. On a Mac, allow Ruffster in System Settings > Privacy & Security > Local Network.'}, 400)
            return
        if self.path == '/api/import':
            if self.server.private_key is None:
                self._json({'error': 'Unlock the parent key first.'}, 403); return
            try:
                if self.headers.get('Transfer-Encoding'): raise ValueError('unsupported transfer')
                length = int(self.headers.get('Content-Length', '-1'))
                if length < 16 or length > MAX_UPLOAD: raise ValueError('invalid size')
                data = self.rfile.read(length)
                if len(data) != length: raise ValueError('incomplete upload')
                _install_report(self.server, data)
                self._json({'ok': True})
            except Exception:
                self._json({'error': 'The file could not be opened with this parent key, is incomplete, or is larger than 256 MiB.'}, 400)
            return
        self._json({'error': 'Not found'}, 404)


def _install_report(server, data):
    projection, _ = encrypted_view.open_projection_bytes(data, server.private_key)
    projection.close()
    existing = None
    if server.data.is_file():
        current, _ = encrypted_view.open_projection(server.data, server.private_key)
        current.close()
        existing = server.data
    temp_path = None
    try:
        fd, temp_path = tempfile.mkstemp(prefix='.report-', dir=server.folder)
        os.close(fd)
        _copy_validated_ciphertext(data, temp_path, server.private_key, server.retention_days,
                                   existing_path=existing)
        if os.path.getsize(temp_path) > MAX_UPLOAD:
            raise ValueError('merged encrypted report is too large')
        os.replace(temp_path, server.data)
        temp_path = None
    finally:
        if temp_path and os.path.exists(temp_path): os.unlink(temp_path)


def _copy_validated_ciphertext(data, destination, private_key, retention_days=30, *, existing_path=None):
    """Merge unique validated ciphertext within the parent retention window."""
    source = sqlite3.connect(':memory:')
    existing = None
    target = None
    try:
        source.deserialize(data)
        if existing_path is not None:
            uri = Path(existing_path).resolve().as_uri() + '?mode=ro'
            existing = sqlite3.connect(uri, uri=True, timeout=5)
        target = EncryptedAgentStore(destination, private_key.public_key, retention_days)
        versions = {id(source): _snapshot_expiry_version(source)}
        if existing is not None:
            versions[id(existing)] = _snapshot_expiry_version(existing)
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        today = datetime.now(timezone.utc).date().isoformat()
        total_size = 0
        target.db.execute('CREATE TEMP TABLE seen_ciphertexts (digest BLOB PRIMARY KEY) WITHOUT ROWID')
        with target.db:
            for database in (existing, source):
                if database is None:
                    continue
                for expires, ciphertext in database.execute('SELECT expires_on, ciphertext FROM encrypted_events ORDER BY id'):
                    if not isinstance(expires, str) or date.fromisoformat(expires).isoformat() != expires:
                        raise ValueError('invalid expiration day')
                    if not isinstance(ciphertext, bytes) or len(ciphertext) not in CIPHERTEXT_SIZES:
                        raise ValueError('invalid encrypted record size')
                    if expires <= today:
                        continue
                    if versions[id(database)] == LEGACY_EXPIRY_VERSION:
                        try:
                            expires = (date.fromisoformat(expires) - timedelta(days=1)).isoformat()
                        except OverflowError:
                            raise ValueError('invalid expiration day') from None
                        if expires <= today:
                            continue
                    event = encrypted_store.open_event(private_key, ciphertext)
                    at = datetime.fromisoformat(event['at'])
                    if at.tzinfo is None or at.astimezone(timezone.utc) < cutoff:
                        continue
                    identity = hashlib.sha256(ciphertext).digest()
                    inserted = target.db.execute('INSERT OR IGNORE INTO seen_ciphertexts(digest) VALUES (?)',
                                                 (identity,)).rowcount
                    if not inserted:
                        continue
                    total_size += len(ciphertext)
                    if total_size > MAX_UPLOAD:
                        raise ValueError('merged encrypted report is too large')
                    target.db.execute('INSERT INTO encrypted_events(expires_on, ciphertext) VALUES (?, ?)', (expires, ciphertext))
        target.db.execute('DROP TABLE seen_ciphertexts')
    finally:
        if existing is not None: existing.close()
        if target is not None: target.close()
        source.close()


def _snapshot_expiry_version(database):
    columns = {row[1] for row in database.execute('PRAGMA table_info(key_commitment)')}
    if 'expiry_version' not in columns:
        return LEGACY_EXPIRY_VERSION
    versions = database.execute('SELECT expiry_version FROM key_commitment').fetchall()
    if versions == [(LEGACY_EXPIRY_VERSION,)]:
        return LEGACY_EXPIRY_VERSION
    if versions == [(EXPIRY_VERSION,)]:
        return EXPIRY_VERSION
    raise ValueError('unsupported encrypted record expiry version')


def _prune_report_file(path, private_key, retention_days):
    """Atomically remove stale encrypted events without writing plaintext."""
    parent_settings.validate_retention_days(retention_days)
    source = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    target = None
    temp_path = None
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    today = datetime.now(timezone.utc).date().isoformat()

    def keep(expires, ciphertext):
        if not isinstance(expires, str) or date.fromisoformat(expires).isoformat() != expires:
            raise ValueError('invalid expiration day')
        if not isinstance(ciphertext, bytes) or len(ciphertext) not in CIPHERTEXT_SIZES:
            raise ValueError('invalid encrypted record size')
        if expires <= today:
            return False
        event = encrypted_store.open_event(private_key, ciphertext)
        at = datetime.fromisoformat(event['at'])
        return at.tzinfo is not None and at.astimezone(timezone.utc) >= cutoff

    try:
        removed = False
        for expires, ciphertext in source.execute('SELECT expires_on, ciphertext FROM encrypted_events ORDER BY id'):
            if not keep(expires, ciphertext):
                removed = True
        if not removed:
            return 0
        fd, temp_path = tempfile.mkstemp(prefix='.retained-report-', dir=Path(path).parent)
        os.close(fd)
        target = EncryptedAgentStore(temp_path, private_key.public_key, retention_days)
        with target.db:
            for expires, ciphertext in source.execute('SELECT expires_on, ciphertext FROM encrypted_events ORDER BY id'):
                if keep(expires, ciphertext):
                    target.db.execute('INSERT INTO encrypted_events(expires_on, ciphertext) VALUES (?, ?)', (expires, ciphertext))
        target.close(); target = None
        source.close(); source = None
        os.replace(temp_path, path); temp_path = None
        return 1
    finally:
        if source is not None:
            source.close()
        if target is not None:
            target.close()
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


def _remove_device_records(path, private_key, retention_days, device_id):
    """Atomically remove one computer and its parent-authenticated name event."""
    parent_settings.validate_retention_days(retention_days)
    source_path = Path(path).expanduser()
    if source_path.is_symlink() or not source_path.is_file():
        raise ValueError('parent report is not a regular file')
    _prune_report_file(source_path, private_key, retention_days)
    projection, _ = encrypted_view.open_projection(source_path, private_key)
    try:
        known_devices = {row[0] for row in projection.execute('SELECT DISTINCT device_id FROM sessions')}
    finally:
        projection.close()
    if not isinstance(device_id, str) or device_id not in known_devices:
        raise ValueError('computer is not in this report')

    source = sqlite3.connect(source_path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    temp_path = None
    identity_sidecar = None
    target = None
    removed = 0
    try:
        descriptor, temporary = tempfile.mkstemp(prefix='.remove-computer-', dir=source_path.parent)
        os.close(descriptor)
        temp_path = temporary
        identity_sidecar = Path(temp_path + '.device-id')
        target = EncryptedAgentStore(temp_path, private_key.public_key, retention_days)
        with target.db:
            for expires, ciphertext in source.execute(
                    'SELECT expires_on, ciphertext FROM encrypted_events ORDER BY id'):
                if (not isinstance(expires, str) or date.fromisoformat(expires).isoformat() != expires
                        or not isinstance(ciphertext, bytes) or len(ciphertext) not in CIPHERTEXT_SIZES):
                    raise ValueError('invalid encrypted record')
                event = encrypted_store.open_event(private_key, ciphertext)
                if event.get('type') == 'device_label':
                    remove = event.get('target_device_id') == device_id
                else:
                    remove = encrypted_view._device_id(event) == device_id
                if remove:
                    removed += 1
                    continue
                target.db.execute(
                    'INSERT INTO encrypted_events(expires_on,ciphertext) VALUES (?,?)',
                    (expires, ciphertext))
        target.close()
        target = None
        source.close()
        source = None
        os.replace(temp_path, source_path)
        temp_path = None
        return removed
    finally:
        if source is not None:
            source.close()
        if target is not None:
            target.close()
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
        if identity_sidecar:
            identity_sidecar.unlink(missing_ok=True)


def _report(path, private_key, labels_path, schedule_path, selected_device=None):
    db, incomplete = encrypted_view.open_projection(path, private_key)
    try:
        now = datetime.now(timezone.utc)
        device_rows = db.execute(
            'SELECT device_id, MAX(heartbeat_at) FROM sessions GROUP BY device_id '
            'ORDER BY MAX(heartbeat_at) DESC, device_id').fetchall()
        saved_device_labels = dict(db.execute('SELECT device_id, label FROM device_labels'))
        devices = []
        for identifier, last_seen in device_rows:
            default_label = ('Older untagged records' if identifier == 'legacy'
                             else f'Computer ending {identifier[-4:].upper()}')
            devices.append({'device_id': identifier,
                            'label': saved_device_labels.get(identifier, default_label),
                            'last_seen': last_seen})
        incomplete_devices = {row[0] for row in db.execute(
            "SELECT device_id FROM sessions WHERE started_at = 'Start unavailable'")}
        if selected_device is not None:
            if not isinstance(selected_device, str) or selected_device not in {row[0] for row in device_rows}:
                raise ValueError('unknown computer selection')
            # The projection is memory-only. Remove other devices there so every
            # report query, including coverage and network context, stays scoped.
            for table in ('foreground_samples', 'network_intervals', 'website_samples',
                          'network_settings', 'network_changes', 'gaps',
                          'process_network_samples', 'process_network_status'):
                db.execute(f'DELETE FROM {table} WHERE session_id NOT IN '
                           '(SELECT id FROM sessions WHERE device_id = ?)', (selected_device,))
            db.execute('DELETE FROM sessions WHERE device_id != ?', (selected_device,))
            incomplete = selected_device in incomplete_devices
        db.commit()
        cutoff = (now - timedelta(days=8)).isoformat()
        apps = db.execute("SELECT session_id, sampled_at, app_name, bundle_id FROM foreground_samples WHERE sampled_at >= ? ORDER BY session_id, sampled_at, id", (cutoff,)).fetchall()
        sites = db.execute("SELECT session_id, sampled_at, domain, '' FROM website_samples WHERE sampled_at >= ? ORDER BY session_id, sampled_at, id", (cutoff,)).fetchall()
        website_observations = db.execute(
            'SELECT COUNT(*), MAX(sampled_at) FROM website_samples WHERE sampled_at >= ?',
            (cutoff,)).fetchone()
        gaps = db.execute('SELECT from_at, to_at FROM gaps ORDER BY id DESC LIMIT 20').fetchall()
        sessions = db.execute('SELECT started_at, heartbeat_at, stopped_at FROM sessions ORDER BY id DESC LIMIT 20').fetchall()
        runtime_sessions = db.execute('SELECT started_at, heartbeat_at, stopped_at, restarted_after_unclean_exit FROM sessions WHERE heartbeat_at >= ? OR stopped_at >= ?', (cutoff, cutoff)).fetchall()
        runtime_gaps = db.execute('SELECT from_at, to_at FROM gaps WHERE to_at >= ? AND from_at <= ?', (cutoff, now.isoformat())).fetchall()
        traffic = db.execute('SELECT to_at, interface, received_bytes, sent_bytes FROM network_intervals ORDER BY id DESC LIMIT 20').fetchall()
        traffic_interval_rows = db.execute(
            'SELECT session_id, from_at, to_at, interface, received_bytes, sent_bytes '
            'FROM network_intervals WHERE to_at >= ? AND to_at <= ? ORDER BY to_at',
            ((now - timedelta(days=9)).isoformat(), now.isoformat())).fetchall()
        traffic_intervals = [row[1:] for row in traffic_interval_rows]
        process_samples = db.execute(
            'SELECT sampled_at, process_name, received_bytes, sent_bytes FROM process_network_samples '
            'WHERE sampled_at >= ? AND sampled_at <= ? ORDER BY sampled_at',
            ((now - timedelta(days=8)).isoformat(), now.isoformat())).fetchall()
        process_network_status = db.execute(
            'SELECT state, sampled_at FROM process_network_status ORDER BY sampled_at DESC, id DESC LIMIT 1').fetchone()
        timestamps = [db.execute('SELECT MAX(value) FROM (SELECT started_at AS value FROM sessions UNION ALL SELECT heartbeat_at FROM sessions UNION ALL SELECT stopped_at FROM sessions)').fetchone()[0]]
        for query in (
            'SELECT MAX(sampled_at) FROM foreground_samples',
            'SELECT MAX(sampled_at) FROM website_samples',
            'SELECT MAX(sampled_at) FROM process_network_samples',
            'SELECT MAX(to_at) FROM network_intervals',
            'SELECT MAX(sampled_at) FROM network_settings',
            'SELECT MAX(sampled_at) FROM network_changes',
        ):
            timestamps.append(db.execute(query).fetchone()[0])
        parsed_timestamps = []
        for value in timestamps:
            try:
                parsed = datetime.fromisoformat(value)
                if parsed.tzinfo is not None:
                    parsed_timestamps.append(parsed.astimezone(timezone.utc))
            except (TypeError, ValueError):
                continue
        recorded_through = max(parsed_timestamps).isoformat() if parsed_timestamps else None
        settings = db.execute('SELECT sampled_at, dns_observed, proxy_indicator, vpn_indicator FROM network_settings ORDER BY id DESC LIMIT 1').fetchone()
        network_settings = None if settings is None else {
            'sampled_at': settings[0],
            'dns_observed': None if settings[1] is None else bool(settings[1]),
            'proxy_indicator': None if settings[2] is None else bool(settings[2]),
            'vpn_indicator': None if settings[3] is None else bool(settings[3]),
        }
        identifiers = db.execute('SELECT identifier, MAX(sampled_at) FROM network_changes WHERE identifier IS NOT NULL GROUP BY identifier ORDER BY MAX(sampled_at) DESC LIMIT 50').fetchall()
        labels = network_labels.load(labels_path, private_key)
        networks = [{'identifier': token, 'last_seen': last_seen, 'label': labels.get(token)} for token, last_seen in identifiers]
        changes = db.execute('SELECT session_id, sampled_at, identifier FROM network_changes ORDER BY session_id, sampled_at, id').fetchall()
        schedule = school_schedule.load(schedule_path, private_key)
        calendar_timezone = ZoneInfo(schedule['timezone']) if schedule else None
        report_timezone = schedule['timezone'] if schedule else 'Local time zone'
        contexts = {'apps': reports.contextual_estimates(apps, changes, labels, schedule, now),
                    'sites': reports.contextual_estimates(sites, changes, labels, schedule, now),
                    'schedule_configured': schedule is not None}
        app_estimates = reports.estimates(apps, now, calendar_timezone=calendar_timezone)
        site_estimates = reports.estimates(sites, now, calendar_timezone=calendar_timezone)
        site_categories = {period: website_categories.aggregate(rows) for period, rows in site_estimates.items()}
        category_contexts = {period: website_categories.aggregate(contexts['sites'][period])
                             for period in ('school', 'home', 'school_network', 'other_network')}
        result = {'incomplete': incomplete, 'devices': devices,
                  'selected_device': selected_device, 'apps': app_estimates, 'sites': site_estimates,
                  'website_observations': {'count': website_observations[0],
                                           'latest_at': website_observations[1]},
                  'site_categories': site_categories, 'category_contexts': category_contexts,
                  'gaps': gaps, 'sessions': sessions,
                  'agent_runtime': reports.agent_runtime(runtime_sessions, runtime_gaps, now),
                  'traffic': traffic,
                  'traffic_usage': reports.traffic_usage(traffic_intervals, now, calendar_timezone),
                  'traffic_contexts': reports.contextual_traffic_usage(
                      traffic_interval_rows, changes, labels, schedule, now),
                  'process_traffic': {'status': process_network_status[0] if process_network_status else None,
                                      'status_at': process_network_status[1] if process_network_status else None,
                                      **reports.process_traffic(process_samples, now, calendar_timezone)},
                  'networks': networks,
                  'network_settings': network_settings, 'contexts': contexts,
                  'recorded_through': recorded_through, 'generated_at': now.isoformat(),
                  'report_timezone': report_timezone}
        result['conversation_prompts'] = _conversation_prompts(result)
        return result
    finally:
        db.close()


def _conversation_prompts(report):
    """Suggest context questions from observations; never classify behavior."""
    prompts = []
    if not report['sessions']:
        prompts.append('No recent Ruffster sessions are in this report. Check when the report was last shared and whether Ruffster is running.')
    if report['incomplete']:
        prompts.append('This report starts partway through a session, so earlier activity may not be included.')
    if report['gaps']:
        prompts.append('Ruffster marked time without observations. Was the computer asleep, turned off, or updating then?')
    if any(network['label'] is None for network in report['networks']):
        prompts.append('There’s a new network to label. Does it look like Home, School, or Other?')
    settings = report['network_settings']
    if settings is None:
        prompts.append('No recent network settings are in this report. Your filter provider can show whether protection is active.')
    else:
        if settings['proxy_indicator'] is True or settings['vpn_indicator'] is True:
            prompts.append('A proxy or VPN setting appeared. Does that match the school or home computer setup?')
        prompts.append('Ruffster shares a few network indicators. Check your filter provider on school Wi-Fi and hotspots too if you want to confirm it is active there.')
    if not prompts:
        prompts.append('Want to add more context? Look together at the estimated time, app names, and any website details.')
    return prompts


def _write_launcher_url(path, url):
    """Publish a short-lived loopback session URL for a native launcher."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(url)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try: os.unlink(path)
        except OSError: pass
        raise


def run(folder, port=0, open_browser=True, url_file=None, stop_file=None):
    server = ParentServer(folder, port)
    def stop_on_termination(signum, frame):
        raise KeyboardInterrupt
    previous_termination = signal.signal(signal.SIGTERM, stop_on_termination)
    try:
        print(f'Parent app is running on 127.0.0.1:{server.server_port}. Press Ctrl-C to close.', flush=True)
        if url_file:
            _write_launcher_url(url_file, server.url)
        elif open_browser:
            if not webbrowser.open(server.url):
                print('Could not open a browser. Restart the app after checking your browser settings.', flush=True)
        else:
            print(server.url, flush=True)  # Explicit developer mode only; URL grants access.
        if stop_file:
            server.timeout = 0.5
            while not Path(stop_file).exists():
                server.handle_request()
        else:
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, previous_termination)
        server.stop_public_key_share()
        server.private_key = None
        server.server_close()
        for path in (url_file, stop_file):
            if path:
                try: Path(path).unlink(missing_ok=True)
                except OSError: pass
