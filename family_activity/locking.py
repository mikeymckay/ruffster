"""Exclusive per-database process lock using native OS locking primitives."""
import os


def lock_file(stream):
    if os.name == 'nt':
        import msvcrt
        # Windows locks a byte range. Ensure one byte exists and seek to it.
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write('0')
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise BlockingIOError('database already has an agent') from exc
    else:
        import fcntl
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
