#!/usr/bin/env python3
"""Exercise parent-key backup recovery using a packaged FamilyActivityCore binary.

The script creates two throwaway parent data directories, restores an encrypted
key backup from the first into the second, checks the public key is unchanged,
and removes the temporary directories. It never starts the monitoring agent.
"""
import argparse
import base64
import http.client
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
from urllib.parse import urlsplit


PASSPHRASE = "638204"


def start_parent(binary, data_dir):
    process = subprocess.Popen(
        [str(binary), "parent", "--no-browser", "--data-dir", str(data_dir)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        startup = process.stdout.readline().strip()
        session_url = process.stdout.readline().strip()
        parsed = urlsplit(session_url)
        if (process.poll() is not None or not startup.startswith("Parent app is running on ")
                or parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
                or not parsed.port or not parsed.fragment):
            error = process.stderr.read().strip()
            raise RuntimeError(f"packaged parent app did not start: {error or startup}")
        return process, parsed, parsed.fragment
    except BaseException:
        stop_parent(process)
        raise


def stop_parent(process):
    if process.poll() is None:
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    if process.stdout:
        process.stdout.close()
    if process.stderr:
        process.stderr.close()


def request(parsed, method, path, body=None, cookie=None, token=None):
    connection = http.client.HTTPConnection("127.0.0.1", parsed.port, timeout=10)
    headers = {"Host": f"127.0.0.1:{parsed.port}"}
    if method == "POST":
        headers["Origin"] = f"http://127.0.0.1:{parsed.port}"
        headers["Content-Type"] = "application/json"
    if cookie:
        headers["Cookie"] = cookie
    if path == "/api/login":
        body = {"token": token}
    encoded = json.dumps(body).encode() if isinstance(body, dict) else body
    connection.request(method, path, encoded, headers)
    response = connection.getresponse()
    content = response.read()
    status = response.status
    response_headers = dict(response.getheaders())
    connection.close()
    if status < 200 or status >= 300:
        try:
            reason = json.loads(content).get("error", "request failed")
        except (ValueError, AttributeError):
            reason = "request failed"
        raise RuntimeError(f"{method} {path} returned {status}: {reason}")
    return response_headers, content


def login(parsed, token):
    headers, _ = request(parsed, "POST", "/api/login", token=token)
    return headers["Set-Cookie"].split(";", 1)[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("core", type=Path, help="Path to packaged FamilyActivityCore executable")
    args = parser.parse_args()
    binary = args.core.expanduser().resolve()
    if not binary.is_file() or not os.access(binary, os.X_OK):
        parser.error("core must be an executable packaged FamilyActivityCore binary")

    first = second = None
    with tempfile.TemporaryDirectory(prefix="family-activity-recovery-") as temporary:
        root = Path(temporary)
        os.chmod(root, 0o700)
        try:
            first, first_url, first_token = start_parent(binary, root / "original-parent")
            first_cookie = login(first_url, first_token)
            request(first_url, "POST", "/api/create",
                    {"passphrase": PASSPHRASE, "confirm": PASSPHRASE}, first_cookie)
            _, backup = request(first_url, "GET", "/api/backup", cookie=first_cookie)
            _, expected_public = request(first_url, "GET", "/api/public", cookie=first_cookie)
            stop_parent(first)
            first = None

            second, second_url, second_token = start_parent(binary, root / "restored-parent")
            second_cookie = login(second_url, second_token)
            request(second_url, "POST", "/api/restore-key",
                    {"backup": base64.b64encode(backup).decode("ascii"),
                     "passphrase": PASSPHRASE}, second_cookie)
            _, restored_public = request(second_url, "GET", "/api/public", cookie=second_cookie)
            _, status_bytes = request(second_url, "GET", "/api/status", cookie=second_cookie)
            status = json.loads(status_bytes)
            if restored_public != expected_public or not status["unlocked"]:
                raise RuntimeError("restored key does not match the original parent key")
            if (root / "original-parent").stat().st_mode & 0o077:
                raise RuntimeError("parent data directory permissions are too broad")
            if (root / "restored-parent").stat().st_mode & 0o077:
                raise RuntimeError("restored data directory permissions are too broad")
            print("PASS: packaged parent app created a key backup, restored it into a fresh profile, and unlocked the same public key.")
            print("PASS: both temporary parent data directories were private (mode 0700 or stricter).")
            print("PASS: temporary files are removed when this command exits; no monitoring agent was started.")
        finally:
            if second is not None:
                stop_parent(second)
            if first is not None:
                stop_parent(first)


if __name__ == "__main__":
    main()
