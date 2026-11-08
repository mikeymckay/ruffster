"""macOS adapters. Return unknown on errors; never infer per-website traffic."""
import json
import subprocess


def parse_netstat(output):
    """Read each interface's link-layer row once; counters are cumulative bytes."""
    rows = output.splitlines()
    if not rows:
        return {}
    header = rows[0].split()
    try:
        name_index, network_index = header.index('Name'), header.index('Network')
        header.index('Ibytes'); header.index('Obytes')
    except ValueError:
        return {}
    result = {}
    for line in rows[1:]:
        columns = line.split()
        if len(columns) < 10:
            continue
        name = columns[name_index].rstrip('*')
        if not columns[network_index].startswith('<Link#') or name.startswith('lo'):
            continue
        try:
            result[name] = (int(columns[-5]), int(columns[-2]))
        except ValueError:
            continue
    return result


def network_counters():
    try:
        output = subprocess.run(['/usr/sbin/netstat', '-ibn'], capture_output=True,
                                text=True, timeout=5, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    counters = parse_netstat(output)
    return counters or None


def traffic_delta(previous, current):
    """Only compare interfaces present in both samples; resets are unknown."""
    result = {}
    for interface in previous.keys() & current.keys():
        old_rx, old_tx = previous[interface]
        rx, tx = current[interface]
        if rx >= old_rx and tx >= old_tx:
            result[interface] = (rx - old_rx, tx - old_tx)
    return result


def foreground_application(helper):
    """Return application identity, or None if unavailable or malformed."""
    try:
        result = subprocess.run([helper], capture_output=True, text=True,
                                timeout=5, check=True)
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            return None
        name, bundle_id = value.get("name"), value.get("bundle_id")
        if not isinstance(name, str) or not isinstance(bundle_id, str):
            return None
        if not name and not bundle_id:
            return None
        return name, bundle_id
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
