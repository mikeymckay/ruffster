"""Typed public-key exchange format to reduce accidental private-key selection."""
from nacl.public import PublicKey

MAGIC = b'FAMILY-ACTIVITY-PUBLIC-KEY-V1\n'


def encode(key):
    if not isinstance(key, PublicKey):
        raise TypeError('a public key is required')
    return MAGIC + bytes(key)


def decode(data, *, allow_legacy=False):
    if data.startswith(MAGIC) and len(data) == len(MAGIC) + PublicKey.SIZE:
        return PublicKey(data[len(MAGIC):])
    if allow_legacy and len(data) == PublicKey.SIZE:
        return PublicKey(data)
    raise ValueError('not a Family Activity public-key file')
