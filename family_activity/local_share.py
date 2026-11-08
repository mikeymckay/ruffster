"""Experimental one-time encrypted snapshot transfer over pinned TLS.

A code received in person carries the server certificate fingerprint and a
one-use bearer token. This is not an authenticated installation or a defense
against a compromised child computer, and requires independent security review.
"""
import base64
from datetime import date, datetime, timedelta, timezone
import hashlib
import hmac
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
import ipaddress
import select
import json
import os
from pathlib import Path
import re
import secrets
import socket
from socketserver import TCPServer
import sqlite3
import ssl
import tempfile
import threading
import time
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from .encrypted_store import CIPHERTEXT_SIZES
from .encrypted_agent_store import EXPIRY_VERSION, LEGACY_EXPIRY_VERSION
from .limits import MAX_SNAPSHOT_BYTES
from . import public_key_file

MAX_SNAPSHOT = MAX_SNAPSHOT_BYTES
ALLOWED = tuple(ipaddress.ip_network(x) for x in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','169.254.0.0/16','127.0.0.0/8'))
DISCOVERY_PORT = 49372
DISCOVERY_BROADCAST = '255.255.255.255'


def _address(value):
    try: address = ipaddress.IPv4Address(value)
    except (ipaddress.AddressValueError, TypeError): raise ValueError('an IPv4 local address is required') from None
    if not any(address in net for net in ALLOWED): raise ValueError('only local IPv4 addresses are allowed')
    return str(address)


def encode_code(host, port, fingerprint, token):
    obj = {'v':1, 'host':_address(host), 'port':port, 'fingerprint':fingerprint, 'token':token}
    raw = json.dumps(obj, separators=(',', ':')).encode('ascii')
    code = base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')
    decode_code(code)
    return code


def decode_code(code):
    if not isinstance(code, str) or len(code) > 1024 or not re.fullmatch(r'[A-Za-z0-9_-]+', code):
        raise ValueError('invalid connection code')
    try:
        obj = json.loads(base64.urlsafe_b64decode(code + '=' * (-len(code) % 4)))
        if not isinstance(obj, dict) or set(obj) != {'v','host','port','fingerprint','token'} or type(obj['v']) is not int or obj['v'] != 1:
            raise ValueError('invalid code')
        obj['host'] = _address(obj['host'])
        if type(obj['port']) is not int or not 1 <= obj['port'] <= 65535:
            raise ValueError('invalid port')
        if not isinstance(obj['fingerprint'], str) or not re.fullmatch(r'[0-9a-f]{64}', obj['fingerprint']):
            raise ValueError('invalid fingerprint')
        if not isinstance(obj['token'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', obj['token']):
            raise ValueError('invalid token')
        return obj
    except (ValueError, TypeError, KeyError):
        raise ValueError('invalid connection code') from None


class _LanCodeAnnouncer:
    """Resolve a short nearby-device number to the existing pinned TLS code."""
    def __init__(self, connection_code, lifetime):
        self.pin = f'{secrets.randbelow(100):02d}'
        self.connection_code = connection_code
        self.deadline = time.monotonic() + lifetime
        self.stopped = threading.Event()
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(('', DISCOVERY_PORT))
        self.socket.settimeout(0.2)
        self.thread = threading.Thread(target=self._run, daemon=True, name='family-local-discovery')
        self.thread.start()

    def _run(self):
        while not self.stopped.is_set() and time.monotonic() < self.deadline:
            try:
                raw, address = self.socket.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                request = json.loads(raw.decode('ascii'))
                if (not isinstance(request, dict) or set(request) != {'v', 'pin', 'nonce'}
                        or type(request['v']) is not int or request['v'] != 1
                        or not isinstance(request['pin'], str)
                        or not hmac.compare_digest(request['pin'], self.pin)
                        or not isinstance(request['nonce'], str)
                        or not re.fullmatch(r'[A-Za-z0-9_-]{22}', request['nonce'])):
                    continue
                response = json.dumps({'v': 1, 'pin': self.pin, 'nonce': request['nonce'],
                                       'connection': self.connection_code}, separators=(',', ':'))
                self.socket.sendto(response.encode('ascii'), address)
            except (UnicodeError, ValueError, TypeError, KeyError):
                continue

    def close(self):
        if self.stopped.is_set():
            return
        self.stopped.set()
        try:
            self.socket.close()
        except OSError:
            pass
        if self.thread is not threading.current_thread():
            self.thread.join(timeout=1)


def discover_code(pin, *, timeout=2.0, target=None):
    """Find one matching nearby sender and return its validated pinned-TLS code.

    The two-digit value is a human-friendly device selector, not a secret or an
    authentication factor. Probe only the route-selected local subnet so replies
    are unicast and pass stateful local firewalls; the actual data connection
    still verifies its TLS certificate fingerprint and one-use token.
    """
    if not isinstance(pin, str) or not re.fullmatch(r'[0-9]{2}', pin):
        raise ValueError('enter the two digits shown on the nearby computer')
    if target is None:
        local_address, targets = _local_discovery_targets()
    else:
        local_address, targets = None, (target,)
    nonce = secrets.token_urlsafe(16)
    request = json.dumps({'v': 1, 'pin': pin, 'nonce': nonce}, separators=(',', ':')).encode('ascii')
    matches = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        if local_address is None:
            client.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            client.bind(('', 0))
        else:
            client.bind((local_address, 0))
        client.setblocking(False)
        for address in targets:
            # Nonblocking UDP avoids waiting for an ARP resolution timeout on
            # every host in a local subnet. If the kernel send queue is full,
            # wait briefly for room and retry the same host.
            while True:
                try:
                    client.sendto(request, (address, DISCOVERY_PORT))
                    break
                except BlockingIOError:
                    select.select([], [client], [], 0.05)
        deadline = time.monotonic() + max(0.2, min(timeout, 5.0))
        while time.monotonic() < deadline:
            readable, _, _ = select.select([client], [], [], min(0.1, deadline - time.monotonic()))
            if not readable:
                continue
            try:
                raw, _ = client.recvfrom(4096)
            except BlockingIOError:
                continue
            try:
                response = json.loads(raw.decode('ascii'))
                if (not isinstance(response, dict)
                        or set(response) != {'v', 'pin', 'nonce', 'connection'}
                        or type(response['v']) is not int or response['v'] != 1
                        or response['pin'] != pin or response['nonce'] != nonce):
                    continue
                info = decode_code(response['connection'])
                identity = (info['host'], info['port'], info['fingerprint'], info['token'])
                matches[identity] = response['connection']
            except (UnicodeError, ValueError, TypeError, KeyError):
                continue
    if not matches:
        raise ValueError(
            'No nearby computer matched that code. Check the digits and Wi-Fi. '
            'On a Mac, allow Family Activity under System Settings > Privacy & Security > Local Network.')
    if len(matches) > 1:
        raise ValueError('More than one nearby computer matched. Ask the sender to start a new share and try again.')
    return next(iter(matches.values()))


def _connection_code(value):
    if isinstance(value, str) and re.fullmatch(r'[0-9]{2}', value):
        return discover_code(value)
    decode_code(value)
    return value


def _certificate():
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Family Activity temporary transfer')])
    now = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
                   .public_key(key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
                   .sign(key, hashes.SHA256()))
    cert_pem = certificate.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return cert_pem, key_pem, certificate.fingerprint(hashes.SHA256()).hex()


def encrypted_snapshot(path):
    """Return a consistent, sanitized SQLite image with encrypted records only."""
    source = sqlite3.connect(Path(path).expanduser().resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    target = sqlite3.connect(':memory:')
    try:
        source.execute('BEGIN')
        commitments = source.execute('SELECT fingerprint FROM key_commitment').fetchall()
        if len(commitments) != 1 or not isinstance(commitments[0][0], str) or not re.fullmatch(r'[0-9a-f]{64}', commitments[0][0]):
            raise ValueError('not an encrypted activity database')
        columns = {row[1] for row in source.execute('PRAGMA table_info(key_commitment)')}
        if 'expiry_version' in columns:
            versions = source.execute('SELECT expiry_version FROM key_commitment').fetchall()
            if versions not in ([(LEGACY_EXPIRY_VERSION,)], [(EXPIRY_VERSION,)]):
                raise ValueError('unsupported encrypted record expiry version')
            expiry_version = versions[0][0]
        else:
            expiry_version = LEGACY_EXPIRY_VERSION
        target.execute('CREATE TABLE key_commitment (fingerprint TEXT NOT NULL, expiry_version INTEGER NOT NULL)')
        target.execute('CREATE TABLE encrypted_events (id INTEGER PRIMARY KEY, expires_on TEXT NOT NULL, ciphertext BLOB NOT NULL)')
        target.execute('INSERT INTO key_commitment VALUES (?, ?)', (commitments[0][0], expiry_version))
        total_ciphertext = 0
        for expiry, ciphertext in source.execute('SELECT expires_on, ciphertext FROM encrypted_events ORDER BY id'):
            if not isinstance(expiry, str) or date.fromisoformat(expiry).isoformat() != expiry or not isinstance(ciphertext, bytes) or len(ciphertext) not in CIPHERTEXT_SIZES:
                raise ValueError('invalid encrypted record')
            total_ciphertext += len(ciphertext)
            if total_ciphertext > MAX_SNAPSHOT: raise ValueError('report is too large for transfer')
            target.execute('INSERT INTO encrypted_events(expires_on, ciphertext) VALUES (?, ?)', (expiry, ciphertext))
        target.commit()
        data = target.serialize()
        if len(data) > MAX_SNAPSHOT: raise ValueError('report is too large for transfer')
        return data
    finally:
        source.close(); target.close()


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass
    def do_GET(self):
        header = self.headers.get('Authorization', '')
        expected = 'Bearer ' + self.server.token
        if self.path != '/v1/snapshot' or self.server.used or time.monotonic() >= self.server.deadline or not hmac.compare_digest(header, expected):
            self.send_response(403); self.send_header('Content-Length','0'); self.end_headers(); return
        try:
            data = encrypted_snapshot(self.server.database)
        except Exception:
            self.send_response(503); self.send_header('Content-Length','0'); self.end_headers(); return
        self.server.used = True
        self.send_response(200)
        self.send_header('Content-Type','application/octet-stream')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ShareServer(HTTPServer):
    def handle_error(self, request, client_address):
        # Malformed or disconnected clients must not expose request details in logs.
        pass

    def server_bind(self):
        TCPServer.server_bind(self)
        self.server_name = self.server_address[0]
        self.server_port = self.socket.getsockname()[1]

    def __init__(self, database, host='127.0.0.1', port=0, lifetime=300):
        host = _address(host)
        if not 1 <= lifetime <= 600: raise ValueError('lifetime must be 1 to 600 seconds')
        # Ensure the requested source is an encrypted database before listening.
        encrypted_snapshot(database)
        self.database = Path(database)
        self.token = secrets.token_urlsafe(32)
        self.deadline = time.monotonic() + lifetime
        self.used = False
        self._discovery = None
        self._temporary = tempfile.TemporaryDirectory(prefix='family-share-')
        try:
            cert, key, self.fingerprint = _certificate()
            cert_path = Path(self._temporary.name)/'cert.pem'; key_path = Path(self._temporary.name)/'key.pem'
            cert_path.write_bytes(cert)
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as file: file.write(key)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(cert_path, key_path)
            super().__init__((host, port), _Handler)
            self.socket = context.wrap_socket(self.socket, server_side=True, do_handshake_on_connect=False)
            self.timeout = 1
            self._discovery = _LanCodeAnnouncer(self.code, lifetime)
        except BaseException:
            if hasattr(self, 'socket'):
                try: super().server_close()
                except OSError: pass
            self._temporary.cleanup()
            raise

    @property
    def code(self): return encode_code(self.server_address[0], self.server_port, self.fingerprint, self.token)

    @property
    def short_code(self): return self._discovery.pin

    def get_request(self):
        connection, address = self.socket.accept()
        connection.settimeout(5)
        try:
            connection.do_handshake()
            return connection, address
        except BaseException:
            connection.close()
            raise

    def serve_once(self, cancel_file=None):
        try:
            while (not self.used and time.monotonic() < self.deadline
                   and not (cancel_file and Path(cancel_file).exists())):
                self.handle_request()
        finally:
            self.server_close()

    def server_close(self):
        if self._discovery is not None:
            self._discovery.close()
            self._discovery = None
        super().server_close()
        self._temporary.cleanup()


class _PublicKeyHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        header = self.headers.get('Authorization', '')
        expected = 'Bearer ' + self.server.token
        if (self.path != '/v1/public-key' or self.server.used or
                time.monotonic() >= self.server.deadline or not hmac.compare_digest(header, expected)):
            self.send_response(403); self.send_header('Content-Length', '0'); self.end_headers(); return
        self.server.used = True
        self.send_response(200)
        self.send_header('Content-Type', 'application/vnd.family-activity.public-key')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(self.server.public_key_file)))
        self.end_headers()
        self.wfile.write(self.server.public_key_file)


class PublicKeyShareServer(HTTPServer):
    """One-use, five-minute pinned-TLS transfer of a parent's public key."""
    def handle_error(self, request, client_address):
        pass

    def server_bind(self):
        TCPServer.server_bind(self)
        self.server_name = self.server_address[0]
        self.server_port = self.socket.getsockname()[1]

    def __init__(self, public_key, host, port=0, lifetime=300):
        from nacl.public import PublicKey
        if not isinstance(public_key, PublicKey): raise TypeError('parent public key is required')
        host = _address(host)
        if not 1 <= lifetime <= 600: raise ValueError('lifetime must be 1 to 600 seconds')
        self.public_key_file = public_key_file.encode(public_key)
        self.token = secrets.token_urlsafe(32)
        self.deadline = time.monotonic() + lifetime
        self.used = False
        self._discovery = None
        self._cancelled = threading.Event()
        self._temporary = tempfile.TemporaryDirectory(prefix='family-key-share-')
        try:
            cert, key, self.fingerprint = _certificate()
            cert_path = Path(self._temporary.name) / 'cert.pem'
            key_path = Path(self._temporary.name) / 'key.pem'
            cert_path.write_bytes(cert)
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as file: file.write(key)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(cert_path, key_path)
            super().__init__((host, port), _PublicKeyHandler)
            self.socket = context.wrap_socket(self.socket, server_side=True, do_handshake_on_connect=False)
            self.timeout = 1
            self._discovery = _LanCodeAnnouncer(self.code, lifetime)
        except BaseException:
            if hasattr(self, 'socket'):
                try: super().server_close()
                except OSError: pass
            self._temporary.cleanup()
            raise

    @property
    def code(self): return encode_code(self.server_address[0], self.server_port, self.fingerprint, self.token)

    @property
    def short_code(self): return self._discovery.pin

    def get_request(self):
        connection, address = self.socket.accept()
        connection.settimeout(5)
        try:
            connection.do_handshake()
            return connection, address
        except BaseException:
            connection.close()
            raise

    def serve_once(self):
        try:
            while not self.used and not self._cancelled.is_set() and time.monotonic() < self.deadline:
                self.handle_request()
        finally:
            self.server_close()

    def cancel(self):
        self._cancelled.set()

    def server_close(self):
        if self._discovery is not None:
            self._discovery.close()
            self._discovery = None
        super().server_close()
        self._temporary.cleanup()


def local_ipv4_address():
    """Find the IPv4 source address selected for the default route, without sending data."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect(('192.0.2.1', 80))
        return _address(probe.getsockname()[0])


def _local_discovery_targets():
    """Return the route-selected local IPv4 address and its bounded host list."""
    try:
        import psutil
        local_address = local_ipv4_address()
        for entries in psutil.net_if_addrs().values():
            for entry in entries:
                if (entry.family != socket.AF_INET or entry.address != local_address
                        or not entry.netmask):
                    continue
                network = ipaddress.IPv4Interface(f'{entry.address}/{entry.netmask}').network
                if 2 < network.num_addresses <= 512:
                    return local_address, tuple(str(host) for host in network.hosts())
                break
    except (ImportError, OSError, ValueError, AttributeError):
        pass
    return None, (DISCOVERY_BROADCAST,)


def fetch(code):
    """Verify the out-of-band certificate pin *before* sending the token."""
    return _fetch(_connection_code(code), '/v1/snapshot', 'application/octet-stream', MAX_SNAPSHOT)


def fetch_public_key(code):
    """Receive only a typed public key; a parent private key is never served."""
    try:
        data = _fetch(_connection_code(code), '/v1/public-key', 'application/vnd.family-activity.public-key', 256)
    except OSError:
        raise ValueError('those digits may have expired, or the parent computer cannot be reached') from None
    public_key_file.decode(data)
    return data


def _fetch(code, path, content_type, maximum):
    info = decode_code(code)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # Authentication is the exact out-of-band certificate pin below.
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    with socket.create_connection((info['host'], info['port']), timeout=10) as raw:
        with context.wrap_socket(raw, server_hostname=None) as connection:
            fingerprint = hashlib.sha256(connection.getpeercert(binary_form=True)).hexdigest()
            if not hmac.compare_digest(fingerprint, info['fingerprint']):
                raise ValueError('certificate fingerprint mismatch')
            request = ('GET ' + path + ' HTTP/1.1\r\nHost: ' + info['host'] + ':' + str(info['port']) +
                       '\r\nAuthorization: Bearer ' + info['token'] + '\r\nConnection: close\r\n\r\n')
            connection.sendall(request.encode('ascii'))
            response = http.client.HTTPResponse(connection)
            response.begin()
            if response.status != 200 or response.getheader('Content-Type') != content_type:
                raise ValueError('transfer was not accepted')
            length = int(response.getheader('Content-Length', '-1'))
            if length < 16 or length > maximum: raise ValueError('invalid transfer size')
            data = response.read(length)
            if len(data) != length: raise ValueError('incomplete snapshot')
            return data
