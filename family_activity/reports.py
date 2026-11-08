"""Conservative sample-based summaries; app identity does not prove user activity."""
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
import time as system_time
from zoneinfo import ZoneInfo


def estimates(samples, as_of, max_gap_seconds=30, calendar_timezone=timezone.utc):
    """Return estimates for today and seven calendar days in the chosen zone.

    Credit only intervals with matching known endpoints from the same session.
    This is still an estimate: switching away and back between samples is invisible.
    No time is assigned after the last sample or across long gaps.
    """
    if as_of.tzinfo is None:
        raise ValueError('as_of must be timezone-aware')
    as_of_utc = as_of.astimezone(timezone.utc)
    if calendar_timezone is None:
        # Windows often exposes only a fixed-offset tzinfo from astimezone().
        # mktime delegates wall-time conversion to the OS's current local zone,
        # including its historical daylight-saving rules.
        today = as_of.astimezone().date()
        today_start = _system_local_midnight_utc(today)
        week_start = _system_local_midnight_utc(today - timedelta(days=6))
    else:
        today = as_of.astimezone(calendar_timezone).date()
        today_start = datetime.combine(today, time.min, tzinfo=calendar_timezone).astimezone(timezone.utc)
        week_start = datetime.combine(today - timedelta(days=6), time.min,
                                      tzinfo=calendar_timezone).astimezone(timezone.utc)
    boundaries = {'today': today_start, 'week': week_start}
    totals = {'today': defaultdict(float), 'week': defaultdict(float)}
    previous = {}
    for session, sampled_at, name, bundle_id in samples:
        try:
            timestamp = datetime.fromisoformat(sampled_at)
            if timestamp.tzinfo is None:
                raise ValueError('sample time must be timezone-aware')
            timestamp = timestamp.astimezone(timezone.utc)
        except (ValueError, TypeError):
            previous.pop(session, None)
            continue
        identity = (name, bundle_id) if name or bundle_id else None
        old = previous.get(session)
        previous[session] = (timestamp, identity)
        if not old or not identity or old[1] != identity:
            continue
        start = old[0]
        duration = (timestamp - start).total_seconds()
        if duration <= 0 or duration > max_gap_seconds or timestamp > as_of_utc:
            continue
        for label, boundary in boundaries.items():
            seconds = (timestamp - max(start, boundary)).total_seconds()
            if seconds > 0:
                totals[label][identity] += seconds
    return {label: sorted(((name or bundle, seconds) for (name, bundle), seconds in counts.items()),
                          key=lambda row: (-row[1], row[0]))
            for label, counts in totals.items()}


def traffic_usage(intervals, as_of, calendar_timezone=None):
    """Sum recorded byte deltas by interface for today and seven local days.

    Each short sample interval is assigned to the local date of its end time;
    intervals crossing midnight are not split. Interface totals remain separate
    because virtual, physical, and tunnel counters can overlap.
    """
    if as_of.tzinfo is None:
        raise ValueError('as_of must be timezone-aware')
    end = as_of.astimezone(timezone.utc)
    today = end.astimezone(calendar_timezone).date() if calendar_timezone else end.astimezone().date()
    totals = {'today': defaultdict(lambda: [0, 0]), 'week': defaultdict(lambda: [0, 0])}
    for start_at, finish_at, interface, received, sent in intervals:
        try:
            start = datetime.fromisoformat(start_at)
            finish = datetime.fromisoformat(finish_at)
            if (start.utcoffset() is None or finish.utcoffset() is None or
                    not isinstance(interface, str) or
                    type(received) is not int or type(sent) is not int or
                    received < 0 or sent < 0):
                continue
            start = start.astimezone(timezone.utc)
            finish = finish.astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        if start >= finish or finish > end:
            continue
        local_finish = finish.astimezone(calendar_timezone) if calendar_timezone else finish.astimezone()
        days_ago = (today - local_finish.date()).days
        if days_ago == 0:
            totals['today'][interface][0] += received
            totals['today'][interface][1] += sent
        if 0 <= days_ago < 7:
            totals['week'][interface][0] += received
            totals['week'][interface][1] += sent
    return {period: sorted(((interface, values[0], values[1])
                           for interface, values in per_interface.items()),
                          key=lambda row: row[0])
            for period, per_interface in totals.items()}


def process_traffic(samples, as_of, calendar_timezone=None):
    """Sum sampled process-associated byte deltas by local day and week."""
    if as_of.tzinfo is None:
        raise ValueError('as_of must be timezone-aware')
    end = as_of.astimezone(timezone.utc)
    today = end.astimezone(calendar_timezone).date() if calendar_timezone else end.astimezone().date()
    totals = {'today': defaultdict(lambda: [0, 0]), 'week': defaultdict(lambda: [0, 0])}
    for sampled_at, process, received, sent in samples:
        try:
            timestamp = datetime.fromisoformat(sampled_at)
            if (timestamp.utcoffset() is None or not isinstance(process, str) or not process or
                    type(received) is not int or type(sent) is not int or received < 0 or sent < 0):
                continue
            timestamp = timestamp.astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        if timestamp > end:
            continue
        local_date = timestamp.astimezone(calendar_timezone).date() if calendar_timezone else timestamp.astimezone().date()
        days_ago = (today - local_date).days
        if days_ago == 0:
            totals['today'][process][0] += received
            totals['today'][process][1] += sent
        if 0 <= days_ago < 7:
            totals['week'][process][0] += received
            totals['week'][process][1] += sent
    return {period: sorted(((name, values[0], values[1]) for name, values in per_process.items()),
                           key=lambda row: (-(row[1] + row[2]), row[0]))[:50]
            for period, per_process in totals.items()}


def contextual_traffic_usage(intervals, network_changes, labels, schedule, as_of):
    """Estimate weekly interface bytes in scheduled hours and labeled networks.

    A counter delta cannot be split by time or router exactly, so school-hour
    bytes are apportioned by interval overlap; labeled-network bytes use the most
    recent observed router label. Intervals containing an observed router change
    are omitted from labeled-network estimates. These views can overlap and are
    not additive.
    """
    from bisect import bisect_right
    from .school_schedule import overlap

    if as_of.tzinfo is None:
        raise ValueError('as_of must be timezone-aware')
    end = as_of.astimezone(timezone.utc)
    calendar_timezone = ZoneInfo(schedule['timezone']) if schedule else None
    today = end.astimezone(calendar_timezone).date() if calendar_timezone else end.astimezone().date()
    boundary = today - timedelta(days=6)
    changes = defaultdict(list)
    for session, sampled_at, token in network_changes:
        try:
            timestamp = datetime.fromisoformat(sampled_at)
            if timestamp.utcoffset() is None:
                continue
            changes[session].append((timestamp.astimezone(timezone.utc), token))
        except (TypeError, ValueError):
            continue
    for session, values in changes.items():
        values.sort(key=lambda row: row[0])
        changes[session] = ([row[0] for row in values], [row[1] for row in values])

    totals = {name: defaultdict(lambda: [0, 0])
              for name in ('school', 'home', 'school_network', 'other_network')}
    uncertain = False
    for session, from_at, to_at, interface, received, sent in intervals:
        try:
            start, finish = datetime.fromisoformat(from_at), datetime.fromisoformat(to_at)
            if (start.utcoffset() is None or finish.utcoffset() is None or
                    not isinstance(interface, str) or type(received) is not int or
                    type(sent) is not int or received < 0 or sent < 0):
                continue
            start, finish = start.astimezone(timezone.utc), finish.astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        if start >= finish or finish > end:
            continue
        local_finish = finish.astimezone(calendar_timezone) if calendar_timezone else finish.astimezone()
        if not 0 <= (today - local_finish.date()).days < 7:
            continue
        duration = (finish - start).total_seconds()
        if schedule is not None:
            school_seconds, is_uncertain = overlap(start, finish, schedule)
            uncertain |= is_uncertain
            if school_seconds and not is_uncertain:
                fraction = min(1.0, school_seconds / duration)
                totals['school'][interface][0] += round(received * fraction)
                totals['school'][interface][1] += round(sent * fraction)
        times, tokens = changes.get(session, ([], []))
        index = bisect_right(times, start)
        token = tokens[index - 1] if index else None
        changed_during = index < len(times) and times[index] <= finish
        if not changed_during:
            context = {'home': 'home', 'school': 'school_network',
                       'other': 'other_network'}.get(labels.get(token))
            if context:
                totals[context][interface][0] += received
                totals[context][interface][1] += sent

    result = {period: sorted(((interface, values[0], values[1])
                              for interface, values in per_interface.items()),
                             key=lambda row: row[0])
              for period, per_interface in totals.items()}
    result['schedule_configured'] = schedule is not None
    result['schedule_uncertain'] = uncertain
    return result


def _system_local_midnight_utc(day):
    """Convert local midnight with the operating system's time-zone database."""
    timestamp = system_time.mktime((day.year, day.month, day.day, 0, 0, 0, -1, -1, -1))
    return datetime.fromtimestamp(timestamp, timezone.utc)


def agent_runtime(sessions, gaps, as_of, days=7):
    """Summarize recorded agent session time, excluding known gaps.

    This is process-session coverage, not proof that every collector succeeded
    or that the computer was actively used. Missing session starts are ignored.
    """
    if as_of.tzinfo is None or days < 1:
        raise ValueError('as_of must be timezone-aware and days must be positive')
    end = as_of.astimezone(timezone.utc)
    boundary = end - timedelta(days=days)
    spans = []
    session_count = 0
    for started_at, heartbeat_at, stopped_at in sessions:
        try:
            start = datetime.fromisoformat(started_at)
            last = datetime.fromisoformat(stopped_at or heartbeat_at)
            if start.tzinfo is None or last.tzinfo is None:
                continue
            start = max(start.astimezone(timezone.utc), boundary)
            last = min(last.astimezone(timezone.utc), end)
        except (TypeError, ValueError):
            continue
        if last <= start:
            continue
        session_count += 1
        spans.append((start, last))

    # Merge first so duplicate/corrupt overlapping session boundaries do not
    # inflate runtime. A gap is subtracted only where it overlaps a session.
    merged = []
    for start, finish in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], finish))
        else:
            merged.append((start, finish))
    gap_spans = []
    gap_count = 0
    for from_at, to_at in gaps:
        try:
            start = datetime.fromisoformat(from_at)
            finish = datetime.fromisoformat(to_at)
            if start.tzinfo is None or finish.tzinfo is None:
                continue
            start = max(start.astimezone(timezone.utc), boundary)
            finish = min(finish.astimezone(timezone.utc), end)
        except (TypeError, ValueError):
            continue
        if finish > start:
            gap_count += 1
            gap_spans.append((start, finish))
    merged_gaps = []
    for start, finish in sorted(gap_spans):
        if merged_gaps and start <= merged_gaps[-1][1]:
            merged_gaps[-1] = (merged_gaps[-1][0], max(merged_gaps[-1][1], finish))
        else:
            merged_gaps.append((start, finish))
    gap_total = sum(max(0.0, (min(gap_end, session_end) - max(gap_start, session_start)).total_seconds())
                    for gap_start, gap_end in merged_gaps
                    for session_start, session_end in merged)
    runtime = sum((finish - start).total_seconds() for start, finish in merged)
    return {'seconds': max(0.0, runtime - gap_total),
            'sessions': session_count, 'gaps': gap_count, 'days': days}


def contextual_estimates(samples, network_changes, labels, schedule, as_of, max_gap_seconds=30):
    """Estimate school-hour time and time on family-labeled networks.

    Only consecutive matching observations in a session are credited. Unknown
    network states are not classified by network label. Schedule-based school
    hours and network-label views can overlap and must not be added together.
    Results cover the last seven UTC calendar days.
    """
    from bisect import bisect_right
    from .school_schedule import overlap
    as_of = as_of.astimezone(timezone.utc)
    boundary = as_of.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6)
    changes = defaultdict(list)
    for session, sampled_at, token in network_changes:
        try:
            timestamp = datetime.fromisoformat(sampled_at).astimezone(timezone.utc)
        except (ValueError, TypeError):
            continue
        changes[session].append((timestamp, token))
    for session, values in changes.items():
        values.sort(key=lambda row: row[0])
        changes[session] = ([row[0] for row in values], [row[1] for row in values])
    totals = {name: defaultdict(float)
              for name in ('school', 'home', 'school_network', 'other_network')}

    def add_network_time(identity, token, start, finish):
        context = {'home': 'home', 'school': 'school_network',
                   'other': 'other_network'}.get(labels.get(token))
        if context and finish > start:
            totals[context][identity] += (finish - start).total_seconds()
    previous = {}
    uncertain = False
    for session, sampled_at, name, bundle in samples:
        try:
            timestamp = datetime.fromisoformat(sampled_at).astimezone(timezone.utc)
        except (ValueError, TypeError):
            previous.pop(session, None); continue
        identity = (name, bundle) if name or bundle else None
        old = previous.get(session)
        previous[session] = (timestamp, identity)
        if not old or not identity or old[1] != identity: continue
        start = old[0]
        duration = (timestamp - start).total_seconds()
        if duration <= 0 or duration > max_gap_seconds or timestamp > as_of: continue
        start = max(start, boundary)
        if timestamp <= start: continue
        if schedule is not None:
            school_seconds, ambiguous = overlap(start, timestamp, schedule)
            totals['school'][identity] += school_seconds
            uncertain |= ambiguous
        times, tokens = changes.get(session, ([], []))
        index = bisect_right(times, start)
        # A change is only observed at a sample, not at the time it actually
        # occurred. Skip the whole sample interval if its ending observation
        # reports a change; assigning a precise fraction would invent timing.
        if index < len(times) and times[index] <= timestamp:
            continue
        token = tokens[index - 1] if index else None
        add_network_time(identity, token, start, timestamp)
    values = {label: sorted(((name or bundle, seconds) for (name, bundle), seconds in counts.items() if seconds > 0),
                            key=lambda row: (-row[1], row[0])) for label, counts in totals.items()}
    return {**values, 'schedule_uncertain': uncertain}
