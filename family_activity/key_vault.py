"""Experimental PIN-encrypted parent key backup.

The six-digit PIN is for keeping reports private from a child who does not know
it. It is not strong protection if someone copies the backup and guesses PINs
offline. Keep the recovery copy somewhere only the parent can access.
"""
import os
from pathlib import Path
import re
import stat
import tempfile
from nacl import pwhash, secret, utils
from nacl.public import PrivateKey

MAGIC = b'FAMKEY01'
SALT_SIZE = pwhash.argon2id.SALTBYTES
OPSLIMIT = 3
MEMLIMIT = 64 * 1024 * 1024


def _derive(passphrase, salt):
    if not isinstance(passphrase, str):
        raise TypeError('passphrase must be text')
    return pwhash.argon2id.kdf(secret.SecretBox.KEY_SIZE, passphrase.encode('utf-8'), salt,
                              opslimit=OPSLIMIT, memlimit=MEMLIMIT)


def encrypt_private_key(private_key, passphrase):
    if not isinstance(private_key, PrivateKey):
        raise TypeError('private_key must be a PyNaCl PrivateKey')
    if not isinstance(passphrase, str) or not re.fullmatch(r'[0-9]{6}', passphrase):
        raise ValueError('parent access PIN must be exactly six digits')
    salt = utils.random(SALT_SIZE)
    encrypted = secret.SecretBox(_derive(passphrase, salt)).encrypt(bytes(private_key))
    return MAGIC + salt + bytes(encrypted)


def unlock(blob, passphrase):
    expected_length = len(MAGIC) + SALT_SIZE + secret.SecretBox.NONCE_SIZE + secret.SecretBox.MACBYTES + PrivateKey.SIZE
    if len(blob) != expected_length or not blob.startswith(MAGIC):
        raise ValueError('invalid or unsupported parent key file')
    salt = blob[len(MAGIC):len(MAGIC) + SALT_SIZE]
    encrypted = blob[len(MAGIC) + SALT_SIZE:]
    return PrivateKey(secret.SecretBox(_derive(passphrase, salt)).decrypt(encrypted))


def create_new(path, contents):
    """Create a new private file atomically without replacing an existing path."""
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def replace_existing_private(path, contents):
    """Atomically replace an existing private vault without exposing a partial file."""
    path = Path(path).expanduser()
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('parent key file must be a regular file')
    fd, temporary = tempfile.mkstemp(prefix='.parent-vault-', dir=path.parent)
    try:
        if os.name == 'posix':
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name == 'posix':
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
