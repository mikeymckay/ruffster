"""Chrome native-messaging bridge; reads domain-only frames and never logs them."""
import json
import os
import struct
import sys
from .browser_channel import MAX_MESSAGE, send, validate


def run(source, destination, socket_path):
    while True:
        header = source.read(4)
        if not header:
            return
        if len(header) != 4:
            raise ValueError('truncated native message header')
        length = struct.unpack('=I', header)[0]
        if length > MAX_MESSAGE:
            raise ValueError('native message too large')
        payload = source.read(length)
        if len(payload) != length:
            raise ValueError('truncated native message')
        try:
            message = json.loads(payload.decode('utf-8'))
            validate(message)
            send(socket_path, message)
            result = {'accepted': True}
        except (OSError, ValueError, UnicodeError):
            result = {'accepted': False}
        encoded = json.dumps(result, separators=(',', ':')).encode('ascii')
        destination.write(struct.pack('=I', len(encoded)) + encoded)
        destination.flush()


if __name__ == '__main__':
    path = os.environ.get('FAMILY_ACTIVITY_BROWSER_SOCKET')
    if not path:
        raise SystemExit('browser socket is not configured')
    run(sys.stdin.buffer, sys.stdout.buffer, path)
