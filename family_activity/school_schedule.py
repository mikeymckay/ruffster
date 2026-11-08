"""Parent-selected school hours and conservative UTC interval classification."""
from datetime import date, datetime, time, timedelta, timezone
import os
from pathlib import Path
import re
import tempfile
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .encrypted_store import open_event, seal_event


def validate(value):
    if not isinstance(value, dict) or set(value) != {'timezone', 'days', 'start', 'end'}:
        raise ValueError('invalid school schedule')
    zone, days = value['timezone'], value['days']
    if not isinstance(zone, str) or len(zone) > 100:
        raise ValueError('invalid time zone')
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError('unknown time zone') from None
    if not isinstance(days, list) or not days or any(type(d) is not int or d not in range(7) for d in days) or len(set(days)) != len(days):
        raise ValueError('choose one or more school days')
    for key in ('start', 'end'):
        if not isinstance(value[key], str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value[key]):
            raise ValueError('invalid school time')
    if value['start'] >= value['end']:
        raise ValueError('end time must be after start time on the same day')
    return {'timezone': zone, 'days': sorted(days), 'start': value['start'], 'end': value['end']}


def load(path, key):
    path = Path(path)
    if not path.exists(): return None
    return validate(open_event(key, path.read_bytes()).get('schedule'))


def save(path, key, value):
    schedule = validate(value)
    data = seal_event(key.public_key, {'schedule': schedule})
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.school-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as file:
            file.write(data); file.flush(); os.fsync(file.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
    return schedule


def _boundary(day, clock, zone):
    """Return UTC boundary or None if a local time is ambiguous/nonexistent."""
    naive = datetime.combine(day, time.fromisoformat(clock))
    first, second = (naive.replace(tzinfo=zone, fold=n) for n in (0, 1))
    if first.utcoffset() != second.utcoffset():
        return None
    utc = first.astimezone(timezone.utc)
    if utc.astimezone(zone).replace(tzinfo=None) != naive:
        return None
    return utc


def overlap(start, end, schedule):
    """Return (seconds in school hours, uncertain) for an aware UTC interval."""
    if end <= start: return 0.0, False
    schedule = validate(schedule)
    zone = ZoneInfo(schedule['timezone'])
    local_start = start.astimezone(zone).date()
    local_end = end.astimezone(zone).date()
    total, uncertain = 0.0, False
    day = local_start
    while day <= local_end:
        if day.weekday() in schedule['days']:
            low = _boundary(day, schedule['start'], zone)
            high = _boundary(day, schedule['end'], zone)
            if low is None or high is None or high <= low:
                uncertain = True
            else:
                total += max(0.0, (min(end, high) - max(start, low)).total_seconds())
        day += timedelta(days=1)
    return total, uncertain
