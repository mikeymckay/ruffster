"""Minimized, advisory observations of network configuration.

No resolver IPs, proxy addresses, VPN names, passwords, or URLs are returned.
These observations do not verify filtering or enumerate every VPN/proxy.
"""
import ipaddress
import ntpath
import os
import re
import subprocess

PROXY_FIELDS = frozenset({'HTTPEnable', 'HTTPSEnable', 'SOCKSEnable',
                          'ProxyAutoConfigEnable', 'ProxyAutoDiscoveryEnable'})


def parse_dns(output):
    if not isinstance(output, str) or not re.search(r'^\s*DNS configuration\s*$', output, re.M):
        return None
    for value in re.findall(r'^\s*nameserver\[\d+\]\s*:\s*(\S+)', output, re.M):
        try:
            ipaddress.ip_address(value.split('%', 1)[0])
            return True
        except ValueError:
            continue
    return False


def parse_proxy(output):
    if not isinstance(output, str):
        return None
    values = []
    for name, flag in re.findall(r'^\s*([A-Za-z]+Enable)\s*:\s*(\S+)\s*$', output, re.M):
        if name in PROXY_FIELDS:
            if flag not in {'0', '1'}: return None
            values.append(flag == '1')
    return any(values) if values else None


def parse_vpn(output):
    if not isinstance(output, str):
        return None
    # Presence is informative; absence does not exclude a third-party VPN.
    return True if re.search(r'^\s*\*?\s*\(Connected\)', output, re.M) else None


def parse_windows_vpn(output):
    """Accept only the minimized status token emitted by our PowerShell probe."""
    if not isinstance(output, str):
        return None
    status = output.strip().lower()
    if status == 'connected':
        return True
    if status == 'disconnected':
        return False
    return None


_WINDOWS_VPN_SCRIPT = r"""
$profiles = @()
$queryFailed = $false
try { $profiles += @(Get-VpnConnection -ErrorAction Stop) }
catch { $queryFailed = $true }
try { $profiles += @(Get-VpnConnection -AllUserConnection -ErrorAction Stop) }
catch { $queryFailed = $true }
if ($profiles | Where-Object { $_.ConnectionStatus -eq 'Connected' } | Select-Object -First 1) {
    Write-Output 'connected'
} elseif ($queryFailed) {
    Write-Output 'unknown'
} else {
    Write-Output 'disconnected'
}
"""


def observe_windows_vpn():
    """Check built-in Windows VPN profile state without returning profile data."""
    powershell = ntpath.join(os.environ.get('SystemRoot', r'C:\Windows'),
                             'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
    try:
        result = subprocess.run(
            [powershell, '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', _WINDOWS_VPN_SCRIPT],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5,
            check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_windows_vpn(result.stdout)


def observe_macos():
    def run(*args):
        try:
            return subprocess.run(['/usr/sbin/scutil', *args], capture_output=True,
                                  text=True, timeout=5, check=True).stdout
        except (OSError, subprocess.SubprocessError):
            return None
    return {'dns_observed': parse_dns(run('--dns')),
            'proxy_indicator': parse_proxy(run('--proxy')),
            'vpn_indicator': parse_vpn(run('--nc', 'list'))}


def observe_windows():
    """Return privacy-minimized Windows registry observations.

    Registry strings are examined in memory and never returned. VPN status is
    limited to built-in Windows VPN profiles; third-party VPNs are not covered.
    """
    try:
        import winreg
    except ImportError:
        return {'dns_observed': None, 'proxy_indicator': None, 'vpn_indicator': None}

    dns_observed = None
    proxy_indicator = None
    interfaces_paths = (r'SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces',
                        r'SYSTEM\CurrentControlSet\Services\Tcpip6\Parameters\Interfaces')
    for interfaces_path in interfaces_paths:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, interfaces_path) as interfaces:
                if dns_observed is None:
                    dns_observed = False
                for index in range(winreg.QueryInfoKey(interfaces)[0]):
                    try:
                        name = winreg.EnumKey(interfaces, index)
                        with winreg.OpenKey(interfaces, name) as adapter:
                            for field in ('NameServer', 'DhcpNameServer'):
                                try:
                                    value, _ = winreg.QueryValueEx(adapter, field)
                                except OSError:
                                    continue
                                candidates = value if isinstance(value, (tuple, list)) else str(value).replace(',', ' ').split()
                                if any(_valid_ip(item) for item in candidates):
                                    dns_observed = True
                    except OSError:
                        continue
        except OSError:
            pass

    internet_settings = r'Software\Microsoft\Windows\CurrentVersion\Internet Settings'
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, internet_settings) as settings:
            flags = []
            for field in ('ProxyEnable', 'AutoDetect'):
                try:
                    value, _ = winreg.QueryValueEx(settings, field)
                    if value in (0, 1): flags.append(bool(value))
                except OSError:
                    pass
            # A configured PAC URL indicates proxy configuration; do not read or retain it.
            try:
                value, _ = winreg.QueryValueEx(settings, 'AutoConfigURL')
                if isinstance(value, str): flags.append(bool(value.strip()))
            except OSError:
                pass
            proxy_indicator = any(flags) if flags else None
    except OSError:
        pass
    return {'dns_observed': dns_observed, 'proxy_indicator': proxy_indicator,
            'vpn_indicator': observe_windows_vpn()}


def _valid_ip(value):
    try:
        ipaddress.ip_address(str(value).strip().split('%', 1)[0])
        return True
    except ValueError:
        return False
