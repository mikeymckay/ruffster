"""Opt-in domain-only local channel. No URLs or browser content are accepted."""
import errno
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import stat

MAX_MESSAGE = 1024
DOMAIN = re.compile(r'(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z')


def validate(message):
    if not isinstance(message, dict) or set(message) != {'domain'}:
        raise ValueError('only a domain observation is accepted')
    domain = message['domain']
    if domain is None:
        return None
    if not isinstance(domain, str) or not DOMAIN.fullmatch(domain):
        raise ValueError('invalid domain')
    try:
        ipaddress.ip_address(domain)
    except ValueError:
        return domain
    raise ValueError('IP addresses are not accepted')


class Receiver:
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_absolute():
            raise ValueError('browser socket path must be absolute')
        parent = self.path.parent.stat()
        if parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) & 0o077:
            raise ValueError('browser socket directory must be private to this account')
        if os.path.lexists(path):
            entry = self.path.lstat()
            if not stat.S_ISSOCK(entry.st_mode) or entry.st_uid != os.getuid():
                raise FileExistsError('browser socket path is not an owned socket')
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as probe:
                try:
                    probe.connect(str(self.path))
                except OSError as exc:
                    if exc.errno != errno.ECONNREFUSED:
                        raise
                    # Only remove the exact stale socket we checked.
                    if self.path.lstat().st_ino != entry.st_ino:
                        raise FileExistsError('browser socket changed during check')
                    self.path.unlink()
                else:
                    raise FileExistsError('browser socket is already active')
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            self.socket.bind(str(self.path))
            os.chmod(self.path, 0o600)
            self.identity = self.path.lstat().st_ino
            self.socket.setblocking(False)
        except BaseException:
            self.socket.close()
            raise

    def drain(self):
        for _ in range(128):
            try:
                data = self.socket.recv(MAX_MESSAGE + 1)
            except BlockingIOError:
                return
            if len(data) > MAX_MESSAGE:
                continue
            try:
                yield validate(json.loads(data.decode('utf-8')))
            except (ValueError, UnicodeError):
                continue

    def close(self):
        self.socket.close()
        try:
            if self.path.lstat().st_ino == self.identity:
                self.path.unlink()
        except FileNotFoundError:
            pass


def send(path, message):
    domain = validate(message)
    data = json.dumps({'domain': domain}, separators=(',', ':')).encode('utf-8')
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
        client.settimeout(2)
        client.sendto(data, path)
