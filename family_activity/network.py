"""Compute bounded per-interface counter intervals, without summing interfaces."""
from datetime import datetime
import math
from .macos import traffic_delta


def validate_sampling_interval(interval):
    """Return a finite positive sample interval or reject unsafe loop timing."""
    try:
        interval = float(interval)
    except (TypeError, ValueError, OverflowError):
        raise ValueError('sampling interval must be a finite positive number') from None
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError('sampling interval must be a finite positive number')
    return interval


def sampling_gap_limit(interval):
    """Longest interval considered continuous for sample-based observations."""
    interval = validate_sampling_interval(interval)
    return max(interval * 2, interval + 5)


def coverage_gap(previous_at, previous_monotonic, current_at, current_monotonic, interval):
    """Return an observed UTC interval when at least one clock shows a long pause.

    Wall time catches system sleep on platforms whose monotonic clock pauses
    during sleep. Backwards or naive wall-clock observations stay unknown.
    """
    limit = sampling_gap_limit(interval)
    try:
        previous = datetime.fromisoformat(previous_at)
        current = datetime.fromisoformat(current_at)
        if previous.utcoffset() is None or current.utcoffset() is None:
            return None
        wall_elapsed = (current - previous).total_seconds()
    except (TypeError, ValueError):
        return None
    monotonic_elapsed = current_monotonic - previous_monotonic
    if wall_elapsed <= 0 or monotonic_elapsed < 0 or max(wall_elapsed, monotonic_elapsed) <= limit:
        return None
    return previous_at, current_at


class NetworkSampler:
    def __init__(self, interval):
        self.max_gap = sampling_gap_limit(interval)
        self.previous = None

    def observe(self, counters, timestamp, monotonic):
        """Return (start, end, interface, received, sent) rows or no rows.

        A missing sample breaks continuity. A long interval, clock change, or
        counter reset is unknown rather than attributed to the following sample.
        Zero-byte intervals are omitted to avoid storing inactive interfaces;
        absence is not proof of either zero traffic or full coverage.
        """
        if counters is None:
            self.previous = None
            return []
        current_time = datetime.fromisoformat(timestamp)
        old = self.previous
        self.previous = (counters, timestamp, monotonic)
        if old is None:
            return []
        old_counters, old_timestamp, old_monotonic = old
        wall_elapsed = (current_time - datetime.fromisoformat(old_timestamp)).total_seconds()
        elapsed = monotonic - old_monotonic
        if (elapsed <= 0 or elapsed > self.max_gap or wall_elapsed <= 0
                or wall_elapsed > self.max_gap or abs(wall_elapsed - elapsed) > 2):
            return []
        return [(old_timestamp, timestamp, interface, received, sent)
                for interface, (received, sent) in traffic_delta(old_counters, counters).items()
                if received or sent]
