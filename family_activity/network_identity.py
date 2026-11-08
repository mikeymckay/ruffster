"""Optional, pseudonymous router observation for macOS; not a location claim."""
import hashlib
import hmac
import ipaddress
import re
import subprocess


def parse_route(output):
    fields = {}
    for line in output.splitlines():
        key, separator, value = line.strip().partition(':')
        if separator and key in ('gateway', 'interface'):
            fields[key] = value.strip()
    try:
        gateway = str(ipaddress.IPv4Address(fields['gateway']))
        interface = fields['interface']
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', interface):
            return None
        return gateway, interface
    except (KeyError, ValueError):
        return None


def parse_router_mac(output, gateway):
    # Only trust a line explicitly for the requested address; incomplete ARP
    # entries and address resolution failures remain unknown.
    for line in output.splitlines():
        if f'({gateway})' not in line:
            continue
        match = re.search(r'\bat\s+([0-9a-fA-F]{1,2}(?::[0-9a-fA-F]{1,2}){5})\b', line)
        if match:
            return ':'.join(f'{int(part, 16):02x}' for part in match.group(1).split(':'))
    return None


def identifier(secret, router_mac):
    if len(secret) != 32:
        raise ValueError('network identifier key must be 32 bytes')
    return hmac.new(secret, ('family-activity-router-v1:' + router_mac).encode('ascii'), hashlib.sha256).hexdigest()


def macos_identifier(secret):
    """Observe only the default IPv4 router; do not persist its raw address."""
    try:
        route = subprocess.run(['/sbin/route', '-n', 'get', 'default'], capture_output=True,
                               text=True, timeout=5, check=True)
        parsed = parse_route(route.stdout)
        if not parsed:
            return None
        gateway, interface = parsed
        arp = subprocess.run(['/usr/sbin/arp', '-n', '-i', interface, gateway], capture_output=True,
                             text=True, timeout=5, check=True)
        mac = parse_router_mac(arp.stdout, gateway)
        return identifier(secret, mac) if mac else None
    except (OSError, subprocess.SubprocessError):
        return None
