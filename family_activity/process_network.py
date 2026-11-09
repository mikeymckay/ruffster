"""Small parser and delta accumulator for macOS nettop's per-process totals.

This is an experimental measurement source. It records process-associated byte
deltas only; it does not collect remote addresses, ports, or website names.
"""
import csv
from dataclasses import dataclass
import os
import re
import threading
import time

try:  # These helpers exist only on Unix; this sampler is macOS-only.
    import pty
    import tty
except ImportError:  # Keep the parser and accumulator usable on Windows.
    pty = None
    tty = None


_ROW = re.compile(r'^(?P<name>.+)\.(?P<pid>[0-9]+)$')
_MAX_COUNTER = (1 << 63) - 1


@dataclass(frozen=True)
class ProcessBytes:
    process: str
    received: int
    sent: int


def parse_nettop_line(line):
    """Parse the restricted `-J bytes_in,bytes_out` CSV format."""
    try:
        columns = next(csv.reader([line]))
    except (csv.Error, TypeError):
        return None
    if len(columns) == 4 and columns[-1] == '':
        columns = columns[:3]  # nettop appends an empty CSV column on this macOS release.
    if len(columns) != 3:
        return None
    label = columns[0].strip()
    match = _ROW.fullmatch(label)
    if not match:
        return None  # CSV header, blank row, or unknown process-label format.
    try:
        received, sent = (int(value) for value in columns[1:])
    except ValueError:
        return None
    if not (0 <= received <= _MAX_COUNTER and 0 <= sent <= _MAX_COUNTER):
        return None
    name = match.group('name').strip()
    if not name or len(name) > 128 or any(ord(char) < 32 for char in name):
        return None
    return match.group('pid'), name, received, sent


class ProcessCounterAccumulator:
    """Turn cumulative nettop counters into bounded, process-name byte deltas."""

    def __init__(self, *, clock=time.monotonic, stale_after=60):
        self._clock = clock
        self._stale_after = stale_after
        self._last = {}
        self._pending = {}
        self._last_pruned = clock()

    def observe_line(self, line):
        parsed = parse_nettop_line(line)
        if parsed is None:
            return False
        pid, name, received, sent = parsed
        now = self._clock()
        if now - self._last_pruned >= self._stale_after:
            self._last = {key: counters for key, counters in self._last.items()
                          if now - counters[2] <= self._stale_after}
            self._last_pruned = now
        key = (pid, name)
        previous = self._last.get(key)
        self._last[key] = (received, sent, now)
        if previous is None or now - previous[2] > self._stale_after:
            return True  # First sample is a baseline; do not report old bytes.
        old_received, old_sent, _ = previous
        if received < old_received or sent < old_sent:
            return True  # Counter reset or PID reuse; establish a new baseline.
        received_delta = received - old_received
        sent_delta = sent - old_sent
        if received_delta or sent_delta:
            totals = self._pending.setdefault(name, [0, 0])
            totals[0] = min(_MAX_COUNTER, totals[0] + received_delta)
            totals[1] = min(_MAX_COUNTER, totals[1] + sent_delta)
        return True

    def drain(self):
        result = tuple(ProcessBytes(name, counts[0], counts[1])
                       for name, counts in sorted(self._pending.items()))
        self._pending.clear()
        return result


class MacProcessNetworkSampler:
    """Read process summaries from one bounded-output `nettop` subprocess."""

    def __init__(self, *, popen=None, clock=time.monotonic):
        import shutil
        import subprocess
        import sys

        if sys.platform != 'darwin':
            raise RuntimeError('per-process network sampling is available only on macOS')
        if pty is None or tty is None:
            raise RuntimeError('macOS process sampling needs Unix pseudo-terminal support')
        executable = shutil.which('nettop')
        if not executable:
            raise RuntimeError('macOS nettop is unavailable')
        self._lock = threading.Lock()
        self._accumulator = ProcessCounterAccumulator(clock=clock)
        self._failure = None
        self._closing = threading.Event()
        launch = popen or subprocess.Popen
        self._master_fd, slave_fd = pty.openpty()
        tty.setraw(slave_fd)
        try:
            self._process = launch([executable, '-n', '-L', '0', '-s', '1', '-P', '-x', '-J', 'bytes_in,bytes_out'],
                                   stdin=subprocess.DEVNULL, stdout=slave_fd,
                                   stderr=subprocess.DEVNULL, close_fds=True)
        except BaseException:
            os.close(slave_fd)
            os.close(self._master_fd)
            raise
        os.close(slave_fd)
        self._reader = threading.Thread(target=self._read, name='FamilyActivityNettop', daemon=True)
        self._reader.start()

    def _read(self):
        try:
            pending = bytearray()
            while not self._closing.is_set():
                try:
                    chunk = os.read(self._master_fd, 8192)
                except OSError:
                    break
                if not chunk:
                    break
                pending.extend(chunk)
                while b'\n' in pending:
                    line, _, remainder = pending.partition(b'\n')
                    pending = bytearray(remainder)
                    with self._lock:
                        self._accumulator.observe_line(line.decode('utf-8', errors='replace').strip())
            if not self._closing.is_set():
                code = self._process.poll()
                self._failure = f'macOS nettop stopped unexpectedly (exit {code})'
        except Exception as error:
            if not self._closing.is_set():
                self._failure = f'macOS nettop output could not be read ({type(error).__name__})'

    @property
    def failure(self):
        return self._failure

    def drain(self):
        with self._lock:
            return self._accumulator.drain()

    def close(self):
        if self._closing.is_set():
            return
        self._closing.set()
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except Exception:
                self._process.kill()
                self._process.wait(timeout=2)
        self._reader.join(timeout=2)
        try:
            os.close(self._master_fd)
        except OSError:
            pass
