import argparse
import html
import getpass
import os
from pathlib import Path
import queue
import secrets
import subprocess
import signal
import sqlite3
import threading
import time
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import TCPServer
from datetime import datetime, timedelta, timezone
from . import browser_channel, locking, macos, network, network_identity, network_settings, reports, store, windows


def sampling_interval_argument(value):
    try:
        return network.validate_sampling_interval(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def start_status(helper, share_database=None, *, retention_days=30, interval=15):
    """Require the status process to initialize before collecting snapshots."""
    if sys.platform == 'win32':
        return _start_windows_status(helper, share_database, retention_days, interval)
    environment = os.environ.copy()
    environment["FAMILY_ACTIVITY_PARENT_PID"] = str(os.getpid())
    environment["FAMILY_ACTIVITY_SAMPLE_INTERVAL"] = str(interval)
    if share_database:
        environment["FAMILY_ACTIVITY_SHARE_PYTHON"] = sys.executable
        environment["FAMILY_ACTIVITY_SHARE_DATABASE"] = os.path.abspath(os.path.expanduser(share_database))
        if getattr(sys, 'frozen', False):
            environment["FAMILY_ACTIVITY_SHARE_FROZEN"] = "1"
    process = subprocess.Popen([helper], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, env=environment)
    ready = queue.Queue(maxsize=1)
    def read_ready():
        try:
            ready.put(process.stdout.readline(128))
        except (OSError, ValueError):
            ready.put(b"")
    threading.Thread(target=read_ready, daemon=True).start()
    try:
        try:
            line = ready.get(timeout=10)
        except queue.Empty:
            line = b""
        if line.strip() != b"READY" or process.poll() is not None:
            raise RuntimeError("Status indicator could not start; foreground sampling was not enabled")
        return process
    except BaseException:
        stop_status(process)
        raise


def _start_windows_status(helper, share_database=None, retention_days=30, interval=15):
    """Wait for the GUI tray companion through a private Windows event."""
    import ctypes
    from ctypes import wintypes
    environment = os.environ.copy()
    environment['FAMILY_ACTIVITY_PARENT_PID'] = str(os.getpid())
    event_token = secrets.token_hex(16)
    event_name = 'Local\\FamilyActivity-Ready-' + event_token
    heartbeat_event_name = 'Local\\FamilyActivity-Heartbeat-' + event_token
    environment['FAMILY_ACTIVITY_READY_EVENT'] = event_name
    environment['FAMILY_ACTIVITY_HEARTBEAT_EVENT'] = heartbeat_event_name
    environment['FAMILY_ACTIVITY_RETENTION_DAYS'] = str(retention_days)
    environment['FAMILY_ACTIVITY_SAMPLE_INTERVAL'] = str(interval)
    if share_database:
        environment['FAMILY_ACTIVITY_SHARE_PYTHON'] = sys.executable
        environment['FAMILY_ACTIVITY_SHARE_DATABASE'] = os.path.abspath(os.path.expanduser(share_database))
        if getattr(sys, 'frozen', False):
            environment['FAMILY_ACTIVITY_SHARE_FROZEN'] = '1'
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateEventW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.CreateEventW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    event = kernel.CreateEventW(None, True, False, event_name)
    if not event:
        raise OSError(ctypes.get_last_error(), 'could not create status readiness event')
    process = None
    try:
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        process = subprocess.Popen([helper], env=environment, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, creationflags=flags)
        process._family_activity_heartbeat_event = heartbeat_event_name
        result = kernel.WaitForSingleObject(event, 10000)
        if result != 0 or process.poll() is not None:
            raise RuntimeError('Status indicator could not start; foreground sampling was not enabled')
        return process
    except BaseException:
        stop_status(process)
        raise
    finally:
        kernel.CloseHandle(event)


def stop_status(process):
    if process is not None:
        if getattr(process, 'stdin', None):
            try:
                process.stdin.close()
            except OSError:
                pass
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        if process.stdout:
            process.stdout.close()


def status_heartbeat(process):
    """Tell the native status companion that a complete encrypted sample was stored."""
    if process is None:
        return
    if process.poll() is not None:
        raise RuntimeError("Status indicator stopped; ending experimental monitoring.")
    if sys.platform == 'win32':
        event_name = getattr(process, '_family_activity_heartbeat_event', None)
        if not event_name:
            raise RuntimeError("Status indicator stopped; ending experimental monitoring.")
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenEventW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
        kernel.OpenEventW.restype = wintypes.HANDLE
        kernel.SetEvent.argtypes = (wintypes.HANDLE,)
        kernel.SetEvent.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.restype = wintypes.BOOL
        event = kernel.OpenEventW(0x0002, False, event_name)  # EVENT_MODIFY_STATE
        if not event:
            raise RuntimeError("Status indicator stopped; ending experimental monitoring.")
        try:
            if not kernel.SetEvent(event):
                raise RuntimeError("Status indicator stopped; ending experimental monitoring.")
        finally:
            kernel.CloseHandle(event)
        return
    if process.stdin is None:
        raise RuntimeError("Status indicator stopped; ending experimental monitoring.")
    try:
        process.stdin.write(b"HEARTBEAT\n")
        process.stdin.flush()
    except (BrokenPipeError, OSError, ValueError):
        raise RuntimeError("Status indicator stopped; ending experimental monitoring.") from None


def agent(path, interval, foreground_helper=None, status_helper=None, retention_days=30, monitor_network=False, public_key_path=None, windows_foreground=False, network_key_path=None, browser_socket=None, inspect_network_settings=False):
    interval = network.validate_sampling_interval(interval)
    if not public_key_path:
        raise SystemExit("A parent public key is required; plaintext activity collection is disabled.")
    lock_path = os.path.abspath(os.path.expanduser(path)) + ".lock"
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    lock = open(lock_path, "a")
    try:
        locking.lock_file(lock)
    except BlockingIOError:
        raise SystemExit("An agent is already running for this database")
    status = start_status(status_helper, path if public_key_path else None,
                          retention_days=retention_days, interval=interval) if foreground_helper or monitor_network or windows_foreground or browser_socket or inspect_network_settings else None
    sealed = None
    network_key = None
    receiver = None
    try:
        session_started_at = store.now()
        session_started_monotonic = time.monotonic()
        if network_key_path:
            network_key = Path(network_key_path).read_bytes()
            if len(network_key) != 32:
                raise ValueError("network identifier key must be 32 bytes")
        if browser_socket:
            receiver = browser_channel.Receiver(browser_socket)
        from nacl.public import PublicKey
        from .encrypted_agent_store import EncryptedAgentStore
        public_key = PublicKey(Path(public_key_path).read_bytes())
        sealed = EncryptedAgentStore(path, public_key, retention_days)
        sealed.prune()
        sealed.event("start", at=session_started_at)
        sid = sealed.session_id
    except BaseException:
        if receiver:
            receiver.close()
        if sealed:
            sealed.close()
        stop_status(status)
        lock.close()
        raise
    done = threading.Event()
    def shutdown(signum, frame):
        done.set()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    print(f"Monitoring heartbeat active (session {sid}); Ctrl-C to stop.", flush=True)
    last_observation_at = session_started_at
    last_observation_monotonic = session_started_monotonic
    sampler = network.NetworkSampler(interval) if monitor_network else None
    last_identity = object()
    last_settings = object()
    last_settings_recorded = 0.0
    next_settings_check = 0.0
    next_identity_check = 0.0
    next_sample = time.monotonic() + interval
    try:
        while not done.wait(min(1, max(0, next_sample - time.monotonic()))):
            if status:
                if status.poll() is not None:
                    raise RuntimeError("Status indicator stopped; ending experimental monitoring.")
            if receiver:
                for domain in receiver.drain():
                    sealed.event("website", domain=domain)
            if time.monotonic() < next_sample:
                continue
            next_sample = time.monotonic() + interval
            observed_at = store.now()
            observed_monotonic = time.monotonic()
            gap = network.coverage_gap(last_observation_at, last_observation_monotonic,
                                       observed_at, observed_monotonic, interval)
            if gap:
                sealed.event("gap", from_at=gap[0], to_at=gap[1], at=gap[1])
            last_observation_at = observed_at
            last_observation_monotonic = observed_monotonic
            tick = {}
            extra_network = []
            if foreground_helper or windows_foreground:
                observation = windows.foreground_application() if windows_foreground else macos.foreground_application(foreground_helper)
                tick["application"] = observation
            if sampler:
                counters = windows.network_counters() if sys.platform == 'win32' else macos.network_counters()
                timestamp = store.now()
                observations = sampler.observe(counters, timestamp, time.monotonic())
                if observations:
                    tick["intervals"] = observations[:16]
                    extra_network = observations[16:]
            sealed.event("tick", at=observed_at, **tick)
            for offset in range(0, len(extra_network), 16):
                sealed.event("network", intervals=extra_network[offset:offset + 16])
            if network_key and time.monotonic() >= next_identity_check:
                observed = (network_identity.macos_identifier(network_key) if sys.platform == 'darwin'
                            else windows.network_identifier(network_key) if sys.platform == 'win32'
                            else None)
                next_identity_check = time.monotonic() + 60
                if observed != last_identity:
                    sealed.event("network_identity", identifier=observed)
                    last_identity = observed
            if inspect_network_settings and time.monotonic() >= next_settings_check:
                settings = (network_settings.observe_macos() if sys.platform == 'darwin'
                            else network_settings.observe_windows() if sys.platform == 'win32'
                            else {'dns_observed': None, 'proxy_indicator': None, 'vpn_indicator': None})
                current = time.monotonic()
                if settings != last_settings or current - last_settings_recorded >= 86400:
                    sealed.event("network_settings", **settings)
                    last_settings = settings
                    last_settings_recorded = current
                next_settings_check = current + 300
            sealed.prune()
            if sys.platform in ('darwin', 'win32'):
                status_heartbeat(status)
    finally:
        try:
            try:
                sealed.event("stop")
            finally:
                sealed.close()
        finally:
            if receiver:
                receiver.close()
            stop_status(status)
            lock.close()


class LoopbackHTTPServer(HTTPServer):
    def server_bind(self):
        # HTTPServer performs a reverse DNS lookup here, which can hang on macOS.
        TCPServer.server_bind(self)
        self.server_name = "127.0.0.1"
        self.server_port = self.socket.getsockname()[1]


def dashboard(path, port, private_key_path=None, key_vault_path=None, label_path=None):
    private_key = None
    if private_key_path:
        from nacl.public import PrivateKey
        private_key = PrivateKey(Path(private_key_path).read_bytes())
    elif key_vault_path:
        from .key_vault import unlock
        private_key = unlock(Path(key_vault_path).read_bytes(), getpass.getpass("Parent access PIN (or older phrase): "))

    if label_path and private_key is None:
        raise ValueError("encrypted network labels require parent access")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            # Reject DNS-rebinding hostnames even when they resolve to loopback.
            host = self.headers.get("Host", "").lower()
            port = self.server.server_port
            if host not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
                self.send_error(403)
                return
            if self.path != "/":
                self.send_error(404)
                return
            try:
                if private_key:
                    from .encrypted_view import open_projection
                    from .network_labels import load as load_network_labels
                    labels = load_network_labels(label_path, private_key) if label_path else {}
                    db, incomplete = open_projection(path, private_key)
                else:
                    db, incomplete = store.connect(path), False
                    labels = {}
            except Exception:
                self.send_error(503, "Unable to open activity data with this key")
                return
            try:
                sessions = db.execute("SELECT started_at, heartbeat_at, stopped_at FROM sessions ORDER BY id DESC LIMIT 100").fetchall()
                cutoff = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
                report_samples = db.execute("SELECT session_id, sampled_at, app_name, bundle_id FROM foreground_samples WHERE sampled_at >= ? ORDER BY session_id, sampled_at, id", (cutoff,)).fetchall()
                summaries = reports.estimates(report_samples, datetime.now(timezone.utc))
                website_samples = db.execute("SELECT session_id, sampled_at, domain, '' FROM website_samples WHERE sampled_at >= ? ORDER BY session_id, sampled_at, id", (cutoff,)).fetchall()
                website_summaries = reports.estimates(website_samples, datetime.now(timezone.utc))
                changes = db.execute("SELECT sampled_at, identifier FROM network_changes ORDER BY id DESC LIMIT 100").fetchall()
                changes = [(at, labels.get(token, 'Unknown') if token else 'Unknown', token) for at, token in changes]
                traffic = db.execute("SELECT to_at, interface, received_bytes, sent_bytes FROM network_intervals ORDER BY id DESC LIMIT 100").fetchall()
                samples = db.execute("SELECT sampled_at, app_name, bundle_id FROM foreground_samples ORDER BY id DESC LIMIT 100").fetchall()
                gaps = db.execute("SELECT from_at, to_at FROM gaps ORDER BY id DESC LIMIT 100").fetchall()
            finally:
                db.close()
            def rows(items):
                return "".join("<tr>" + "".join("<td>" + html.escape(str(v) if v is not None else "Unknown or open") + "</td>" for v in row) + "</tr>" for row in items) or '<tr><td colspan="3">No records yet</td></tr>'
            def summary_rows(items):
                return rows([(name, f"{seconds / 60:.1f} min") for name, seconds in items])
            notice = ("<p>Some session starts are unavailable, possibly because older records expired; coverage may be incomplete.</p>" if incomplete else "")
            body = ("<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>Family Activity</title>"
                    "<style>body{font:16px system-ui;max-width:900px;margin:3rem auto;padding:0 1rem;color:#24323a}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:.6rem;border-bottom:1px solid #ddd}small{color:#555}</style>"
                    "<h1>Family Activity</h1><p>Local prototype · timestamps in UTC</p>" + notice +
                    "<p>Heartbeats indicate that the agent ran; they do not prove monitoring coverage. An open session may have stopped unexpectedly. Refresh for updates.</p>"
                    "<h2>Estimated foreground app time</h2><p>UTC calendar days; estimates count only short intervals between matching samples. App switches between samples, locked or idle time, and missing data can make these estimates inaccurate. They are not proof of active use.</p>"
                    "<h3>Today</h3><table><tr><th>Application</th><th>Estimated time</th></tr>" + summary_rows(summaries['today']) + "</table>"
                    "<h3>Last seven days, including today</h3><table><tr><th>Application</th><th>Estimated time</th></tr>" + summary_rows(summaries['week']) + "</table>"
                    "<h2>Estimated website time</h2><p>Optional browser-reported domains, without URL paths or page contents. Time is estimated from nearby matching snapshots and can include idle or locked time; extension disconnects and browser focus changes may cause gaps.</p>"
                    "<h3>Today</h3><table><tr><th>Domain</th><th>Estimated time</th></tr>" + summary_rows(website_summaries['today']) + "</table>"
                    "<h3>Last seven days, including today</h3><table><tr><th>Domain</th><th>Estimated time</th></tr>" + summary_rows(website_summaries['week']) + "</table>"
                    "<h2>Agent sessions</h2><table><tr><th>Started</th><th>Last heartbeat</th><th>Stopped</th></tr>" + rows(sessions) + "</table>"
                    "<h2>Network changes</h2><p>Optional, pseudonymous router identifiers. The same router can serve different networks, and an unavailable router is unknown. An identifier is not proof of location or behavior.</p><table><tr><th>Time (UTC)</th><th>Family label</th><th>Router identifier</th></tr>" + rows(changes) + "</table>"
                    "<h2>Network interface intervals</h2><p>Measured interface counter changes, in bytes, not website or application traffic. Interfaces may overlap (for example a VPN and Wi-Fi), so do not add them together. Missing, reset, and zero-byte counters produce no interval; absence does not prove zero traffic.</p><table><tr><th>Interval ended (UTC)</th><th>Interface</th><th>Received bytes</th><th>Sent bytes</th></tr>" + rows(traffic) + "</table>"
                    "<h2>Foreground samples</h2><p>Samples are snapshots, not measured duration. Missing identities mean the observation was unavailable.</p><table><tr><th>Time</th><th>Application</th><th>Bundle identifier</th></tr>" + rows(samples) + "</table>"
                    "<h2>Unobserved intervals</h2><p>Time between the last heartbeat of an unfinished session and the next start. Cause unknown; this is not evidence of tampering.</p><table><tr><th>Last heartbeat</th><th>Next start</th></tr>" + rows(gaps) + "</table></html>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
    server = LoopbackHTTPServer(("127.0.0.1", port), Handler)
    print(f"Dashboard: http://127.0.0.1:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    win_install = sub.add_parser("windows-install", help="Explicitly install the experimental per-user Windows agent")
    win_install.add_argument("--public-key", required=True, help="Typed public-key file exported by the parent app")
    win_install.add_argument("--python", required=True, help="Absolute path to pythonw.exe or the packaged FamilyActivityCore.exe")
    win_install.add_argument("--source-directory", required=True, help="Absolute directory containing the app runtime")
    win_install.add_argument("--status-helper", required=True, help="Absolute path to the visible tray companion executable")
    win_install.add_argument("--packaged", action="store_true", help="Register the bundled FamilyActivityCore.exe as the agent")
    win_install.add_argument("--retention-days", type=int, choices=(7,30,90,180,365), default=30)
    win_install.add_argument("--disclosed", action="store_true", required=True, help="Confirm that monitoring has been explained to the child")
    win_uninstall = sub.add_parser("windows-uninstall", help="Stop and remove the experimental Windows agent; retain encrypted data by default")
    win_uninstall.add_argument("--delete-data", action="store_true", help="Also delete the local encrypted database and parent public key")
    install_mac = sub.add_parser("mac-install", help="Explicitly install the experimental per-user Mac agent")
    install_mac.add_argument("--public-key", required=True)
    install_mac.add_argument("--source-directory", required=True)
    install_mac.add_argument("--foreground-helper", required=True)
    install_mac.add_argument("--status-helper", required=True)
    install_mac.add_argument("--retention-days", type=int, choices=(7,30,90,180,365), default=30)
    install_mac.add_argument("--disclosed", action="store_true", required=True, help="Confirm that monitoring has been explained to the child")
    mac_uninstall = sub.add_parser("mac-uninstall", help="Stop and remove the Mac agent; retain encrypted data by default")
    mac_uninstall.add_argument("--delete-data", action="store_true", help="Also delete the local encrypted database and parent public key")
    share = sub.add_parser("share", help="Temporarily share one encrypted snapshot on a chosen local interface")
    share.add_argument("--db", required=True)
    share.add_argument("--host", default="127.0.0.1", help="Local IPv4 address to listen on; default loopback only")
    share.add_argument("--port", type=int, default=0)
    share.add_argument("--lifetime", type=int, default=300, help="Maximum seconds to wait, at most 600")
    share.add_argument("--code-file", help="Write the two-digit nearby code to a file for graphical setup tools")
    share.add_argument("--cancel-file", help="Stop a graphical share when this file appears")
    export_report = sub.add_parser("export-report", help="Save a parent-encrypted report copy for transfer by file")
    export_report.add_argument("--db", required=True, help="Encrypted child activity database")
    export_report.add_argument("--output", required=True, help="New report file path")
    export_report.add_argument("--overwrite", action="store_true", help="Replace the selected report file")
    pair_key = sub.add_parser("fetch-public-key", help="Fetch a parent's public key using a two-digit nearby code")
    pair_key.add_argument("--code", help="Two-digit nearby parent code (for graphical setup tools)")
    pair_key.add_argument("--output", help="Write the fetched public key to this temporary path instead of standard output")
    parent = sub.add_parser("parent", help="Open the experimental local parent app")
    parent.add_argument("--data-dir", default=str(Path.home() / ".family-activity-parent"))
    parent.add_argument("--port", type=int, default=0)
    parent.add_argument("--no-browser", action="store_true", help="Developer mode: print a session URL instead of opening it")
    parent.add_argument("--url-file", help="Write a one-run loopback session URL for a native launcher")
    parent.add_argument("--stop-file", help="Stop the local parent server when this file appears")
    a = sub.add_parser("agent", help="Run disclosed monitoring with mandatory parent-key encryption")
    a.add_argument("--db", default="activity.sqlite3")
    a.add_argument("--interval", type=sampling_interval_argument, default=15)
    a.add_argument("--retention-days", type=int, default=30, help="Delete records older than this many days (default: 30).")
    a.add_argument("--experimental-network-settings", action="store_true", help="Observe minimized DNS and proxy indicators on macOS or Windows; VPN detection is incomplete.")
    a.add_argument("--experimental-browser-socket", help="Opt in to domain-only browser observations via a private Unix socket (encrypted mode only).")
    a.add_argument("--experimental-network-key", help="Opt in to a pseudonymous default-router hint with a 32-byte device key; encrypted macOS or Windows mode only.")
    a.add_argument("--experimental-public-key", help="Path to a 32-byte parent public key; use a new database. The private key must stay on the parent device.")
    a.add_argument("--experimental-status-helper", help="Path to compiled macOS status companion, required for app or network sampling.")
    a.add_argument("--experimental-windows-foreground", action="store_true", help="Opt in to experimental Windows foreground application snapshots.")
    a.add_argument("--experimental-network", action="store_true", help="Opt in to experimental macOS interface counter sampling.")
    a.add_argument("--experimental-foreground-helper", help="Developer-only helper that emits a JSON application identity; disclose sampling to the computer user.")
    migration = sub.add_parser("encrypt-legacy", help="Convert a plaintext prototype database into a new parent-key-encrypted copy")
    migration.add_argument("--source", required=True, help="Existing plaintext activity SQLite file (left unchanged)")
    migration.add_argument("--public-key", required=True, help="Parent public-key file; the parent private key is never read here")
    migration.add_argument("--output", required=True, help="New encrypted SQLite output; must not already exist")
    migration.add_argument("--retention-days", type=int, choices=(7, 30, 90, 180, 365), default=30,
                           help="Apply this retention using original observation dates; expired records are omitted (default: 30)")
    d = sub.add_parser("dashboard")
    d.add_argument("--db", default="activity.sqlite3")
    d.add_argument("--port", type=int, default=8765)
    d.add_argument("--experimental-network-labels", help="Parent-held encrypted network labels file")
    key_options = d.add_mutually_exclusive_group()
    key_options.add_argument("--experimental-private-key", help="Parent-side raw private key for development only.")
    key_options.add_argument("--experimental-key-vault", help="Parent-side PIN-protected key file for development only.")
    nl = sub.add_parser("network-label", help="Set a family label for a pseudonymous router identifier")
    nl.add_argument("--vault", required=True)
    nl.add_argument("--labels", required=True)
    nl.add_argument("--identifier", required=True)
    nl.add_argument("--label", choices=("home", "school", "other"), required=True)
    nk = sub.add_parser("network-key", help="Create a device-specific network identifier key for disclosed testing")
    nk.add_argument("--output", required=True)
    k = sub.add_parser("parent-key", help="Experimental parent-device key management")
    k.add_argument("action", choices=("create", "export-public"))
    k.add_argument("--vault", required=True, help="Parent-only encrypted key file")
    k.add_argument("--public", required=True, help="New public-key file to transfer to the child device")
    args = parser.parse_args()
    if args.command in ("windows-install", "windows-uninstall"):
        if sys.platform != 'win32':
            parser.error("Windows installation is available only on Windows")
        from . import windows_install
        if args.command == 'windows-install':
            result = windows_install.install(args.public_key, args.python, args.source_directory, args.status_helper,
                                             retention_days=args.retention_days, packaged=args.packaged)
            print("Windows monitoring started and the visible status companion is ready. Confirm its tray icon is visible.", flush=True)
            print("Encrypted data directory:", result['data_directory'], flush=True)
        else:
            result = windows_install.uninstall(delete_data=args.delete_data)
            print("Agent removed.", "Local encrypted data deleted." if result['data_deleted'] else "Encrypted data retained at " + result['data_retained'], flush=True)
    elif args.command in ("mac-install", "mac-uninstall"):
        if sys.platform != "darwin":
            parser.error("Mac installation is available only on macOS")
        from . import macos_install
        if args.command == "mac-install":
            try:
                result = macos_install.install(args.public_key, sys.executable, args.source_directory,
                                              args.foreground_helper, args.status_helper, Path.home(), os.getuid(),
                                              retention_days=args.retention_days,
                                              frozen=getattr(sys, 'frozen', False))
            except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
                parser.error(str(error))
            print("Experimental agent registered. Verify that the status indicator is visible before use.", flush=True)
            print("Data directory:", result['data_directory'], flush=True)
        else:
            try:
                result = macos_install.uninstall(Path.home(), os.getuid(), delete_data=args.delete_data)
            except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
                parser.error(str(error))
            print("Agent removed.", "Local encrypted data deleted." if result['data_deleted'] else "Encrypted data retained at " + result['data_retained'], flush=True)
    elif args.command == "share":
        from .local_share import ShareServer
        service = ShareServer(args.db, args.host, args.port, args.lifetime)
        def cancel_share(signum, frame):
            raise KeyboardInterrupt
        old_termination = signal.signal(signal.SIGTERM, cancel_share)
        try:
            if args.code_file:
                Path(args.code_file).write_text(service.short_code, encoding='ascii')
            else:
                print("Temporary encrypted report transfer is ready. Show these two digits to your parent:", flush=True)
                print(service.short_code, flush=True)
            service.serve_once(args.cancel_file)
            if not args.code_file:
                print("Transfer complete." if service.used else "Transfer expired without a request.", flush=True)
        except KeyboardInterrupt:
            print("Transfer cancelled.", flush=True)
        finally:
            signal.signal(signal.SIGTERM, old_termination)
            service.server_close()
            for temporary in (args.code_file, args.cancel_file):
                if temporary:
                    try: Path(temporary).unlink(missing_ok=True)
                    except OSError: pass
    elif args.command == "export-report":
        from .local_share import save_encrypted_snapshot
        try:
            size = save_encrypted_snapshot(args.db, args.output, overwrite=args.overwrite)
        except (OSError, ValueError, sqlite3.Error) as error:
            parser.error(str(error))
        print(f"Encrypted report copy saved ({size} bytes). Transfer this file to the parent computer and open it in the parent dashboard.", flush=True)
    elif args.command == "fetch-public-key":
        from .local_share import fetch_public_key
        code = args.code if args.code is not None else sys.stdin.readline(2049).strip()
        data = fetch_public_key(code)
        if args.output:
            Path(args.output).write_bytes(data)
        else:
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
    elif args.command == "parent":
        from .parent_app import run
        run(args.data_dir, args.port, not args.no_browser, args.url_file, args.stop_file)
    elif args.command == "agent":
        if not args.experimental_public_key:
            parser.error("a parent public key is required; plaintext activity collection is disabled")
        if args.interval <= 0:
            parser.error("interval must be positive")
        if args.retention_days < 1:
            parser.error("retention-days must be at least one")
        if args.experimental_network_settings and (sys.platform not in {'darwin', 'win32'} or not args.experimental_public_key or not args.experimental_network):
            parser.error("network settings require macOS or Windows, encrypted storage, and network sampling")
        if args.experimental_browser_socket and (os.name == 'nt' or not args.experimental_public_key):
            parser.error("browser sampling requires Unix and encrypted storage")
        if args.experimental_network_key and (sys.platform not in {'darwin', 'win32'} or not args.experimental_public_key or not args.experimental_network):
            parser.error("router hints require macOS or Windows, encrypted storage, and network sampling")
        if args.experimental_windows_foreground and sys.platform != 'win32':
            parser.error("Windows foreground sampling requires Windows")
        if args.experimental_windows_foreground and args.experimental_foreground_helper:
            parser.error("choose only one foreground adapter")
        if (args.experimental_foreground_helper or args.experimental_network or args.experimental_windows_foreground or args.experimental_browser_socket) and not args.experimental_status_helper:
            parser.error("app or network sampling requires --experimental-status-helper")
        if args.experimental_foreground_helper or args.experimental_network or args.experimental_windows_foreground or args.experimental_browser_socket:
            print("Experimental sampling enabled; use only for disclosed testing.", flush=True)
        agent(args.db, args.interval, args.experimental_foreground_helper, args.experimental_status_helper, args.retention_days, args.experimental_network, args.experimental_public_key, args.experimental_windows_foreground, args.experimental_network_key, args.experimental_browser_socket, args.experimental_network_settings)
    elif args.command == "encrypt-legacy":
        from .plaintext_migration import encrypt_legacy_database
        try:
            result = encrypt_legacy_database(args.source, args.public_key, args.output, args.retention_days)
        except (OSError, ValueError, sqlite3.Error) as error:
            parser.error(str(error))
        print(f"Encrypted copy created: {result['output']}")
        print(f"Retained {result['retained_events']} of {result['inserted_events']} source events across {result['source_sessions']} session(s).")
        print("The original plaintext file was left untouched. Verify the encrypted copy before deciding how to remove the original; secure erasure is not guaranteed.")
    elif args.command == "dashboard":
        dashboard(args.db, args.port, args.experimental_private_key, args.experimental_key_vault, args.experimental_network_labels)
    elif args.command == "network-label":
        from .key_vault import unlock
        from .network_labels import set_label
        parent = unlock(Path(args.vault).read_bytes(), getpass.getpass("Parent access PIN (or older phrase): "))
        set_label(args.labels, parent, args.identifier, args.label)
        print("Family network label saved in encrypted form.")
    elif args.command == "network-key":
        from .key_vault import create_new
        create_new(args.output, os.urandom(32))
        print("Device network identifier key created.")
    else:
        from nacl.public import PrivateKey
        from .key_vault import create_new, encrypt_private_key, unlock
        if args.action == "create":
            password = getpass.getpass("Choose a six-digit parent access PIN: ")
            if password != getpass.getpass("Repeat PIN: "):
                parser.error("PINs do not match")
            private = PrivateKey.generate()
            create_new(args.vault, encrypt_private_key(private, password))
            try:
                create_new(args.public, bytes(private.public_key))
            except Exception:
                print("Parent key file was created; use export-public to retry without replacing it.", flush=True)
                raise
        else:
            private = unlock(Path(args.vault).read_bytes(), getpass.getpass("Parent access PIN (or older phrase): "))
            create_new(args.public, bytes(private.public_key))
        print("Public key exported. Keep the recovery copy and parent PIN on the parent device.", flush=True)

if __name__ == "__main__":
    main()
