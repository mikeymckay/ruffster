"""Experimental Windows observations; no window titles or file paths stored."""
import ntpath
import os
import re
import sys
import subprocess

from .network_identity import identifier


_DEFAULT_ROUTE_SCRIPT = r"""
$interfaceMetrics = @{}
Get-NetIPInterface -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    ForEach-Object {
        $interfaceMetrics[[int]$_.InterfaceIndex] = [int]$_.InterfaceMetric
    }

$routes = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
    Where-Object { $_.NextHop -ne '0.0.0.0' } |
    Sort-Object {
        $metric = 0
        if ($interfaceMetrics.ContainsKey([int]$_.InterfaceIndex)) {
            $metric = $interfaceMetrics[[int]$_.InterfaceIndex]
        }
        [int]$_.RouteMetric + $metric
    }

foreach ($route in $routes) {
    $neighbor = Get-NetNeighbor -AddressFamily IPv4 -InterfaceIndex $route.InterfaceIndex -IPAddress $route.NextHop -ErrorAction SilentlyContinue |
        Where-Object { $_.State -in @('Reachable', 'Stale', 'Delay', 'Probe', 'Permanent') } |
        Select-Object -First 1
    if ($neighbor -and $neighbor.LinkLayerAddress -match '^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$') {
        Write-Output $neighbor.LinkLayerAddress
        exit 0
    }
}
exit 0
"""


def parse_gateway_mac(output):
    """Accept one unicast gateway MAC from the minimized PowerShell result."""
    if not isinstance(output, str):
        return None
    match = re.fullmatch(r'\s*([0-9a-fA-F]{2}(?:[:-][0-9a-fA-F]{2}){5})\s*', output)
    if not match:
        return None
    parts = match.group(1).replace('-', ':').lower().split(':')
    raw = bytes(int(part, 16) for part in parts)
    if raw == bytes(6) or raw == b'\xff' * 6 or raw[0] & 1:
        return None
    return ':'.join(parts)


def network_identifier(secret):
    """Return a device-keyed default-router hint without retaining the MAC/IP.

    Windows PowerShell asks the IP routing and neighbor tables for the active
    IPv4 default gateway's link-layer address. Only a pseudonymous HMAC leaves
    this function; unavailable routes, VPN tunnels, or restricted cmdlets are
    reported as unknown.
    """
    if sys.platform != 'win32':
        return None
    powershell = ntpath.join(os.environ.get('SystemRoot', r'C:\Windows'),
                             'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
    try:
        result = subprocess.run(
            [powershell, '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', _DEFAULT_ROUTE_SCRIPT],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5,
            check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        mac = parse_gateway_mac(result.stdout)
        return identifier(secret, mac) if mac else None
    except (OSError, subprocess.SubprocessError):
        return None


def foreground_application():
    if sys.platform != 'win32':
        return None
    import ctypes
    from ctypes import wintypes
    try:
        user = ctypes.WinDLL('user32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        user.GetForegroundWindow.argtypes = []
        user.GetForegroundWindow.restype = wintypes.HWND
        user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user.GetWindowThreadProcessId.restype = wintypes.DWORD
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        window = user.GetForegroundWindow()
        if not window:
            return None
        pid = wintypes.DWORD()
        if not user.GetWindowThreadProcessId(window, ctypes.byref(pid)) or not pid.value:
            return None
        handle = kernel.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            length = wintypes.DWORD(32768)
            buf = ctypes.create_unicode_buffer(length.value)
            if not kernel.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(length)):
                return None
            name = ntpath.basename(buf.value)
            return (name, '') if name else None
        finally:
            kernel.CloseHandle(handle)
    except (OSError, AttributeError, ValueError):
        return None


def network_counters():
    if sys.platform != 'win32':
        return None
    try:
        import psutil
        # nowrap=False preserves resets so the common sampler can discard them.
        counters = psutil.net_io_counters(pernic=True, nowrap=False)
        if not counters:
            return None
        return {name: (counter.bytes_recv, counter.bytes_sent)
                for name, counter in counters.items()}
    except (ImportError, OSError, AttributeError):
        return None
