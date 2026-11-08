#!/usr/bin/env python3
"""Capture the parent dashboard's first-run PIN screen and a synthetic report.

Requires an installed Chrome/Chromium executable. No agent is started, and all
keys, reports, profiles, and browser data are temporary.
"""
from datetime import datetime, time, timedelta, timezone
import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path
import sys
import threading
from zoneinfo import ZoneInfo

from nacl.public import PrivateKey

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from family_activity.encrypted_agent_store import EncryptedAgentStore
from family_activity import key_vault, network_labels, parent_settings, school_schedule
from family_activity.parent_app import ParentServer


UTC = timezone.utc
LOCAL_ZONE = ZoneInfo('Europe/Vienna')
SCHOOL_ROUTER = 'b' * 64
HOME_ROUTER = 'a' * 64


def stamp(value):
    return value.astimezone(UTC).isoformat(timespec='seconds')


def synthetic_report(database, parent_key, now):
    """Write a handful of fictional weekday sessions and one recent home session."""
    school_days = []
    date_cursor = now.astimezone(LOCAL_ZONE).date() - timedelta(days=1)
    while len(school_days) < 5:
        if date_cursor.weekday() < 5:
            school_days.append(date_cursor)
        date_cursor -= timedelta(days=1)

    for day in reversed(school_days):
        start = datetime.combine(day, time(8, 30), LOCAL_ZONE)
        stop = datetime.combine(day, time(15, 0), LOCAL_ZONE)
        writer = EncryptedAgentStore(database, parent_key.public_key, 30)
        try:
            writer.event('start', at=stamp(start))
            writer.event('network_identity', at=stamp(start + timedelta(minutes=1)), identifier=SCHOOL_ROUTER)
            writer.event('network_settings', at=stamp(start + timedelta(minutes=2)),
                         dns_observed=True, proxy_indicator=False, vpn_indicator=None)
            for begin, finish, application, bundle, domain in (
                (start + timedelta(minutes=15), start + timedelta(minutes=35),
                 'Google Chrome', 'com.google.Chrome', 'classroom.google.com'),
                (start + timedelta(hours=2), start + timedelta(hours=2, minutes=20),
                 'Pages', 'com.apple.Pages', 'docs.google.com'),
            ):
                current = begin
                while current <= finish:
                    writer.event('tick', at=stamp(current), application=[application, bundle])
                    writer.event('website', at=stamp(current), domain=domain)
                    current += timedelta(seconds=15)
            writer.event('network', at=stamp(start + timedelta(hours=1)), intervals=[
                [stamp(start + timedelta(minutes=59, seconds=45)), stamp(start + timedelta(hours=1)),
                 'en0', 1_240_000, 186_000]])
            writer.event('gap', at=stamp(start + timedelta(hours=3, minutes=2)),
                         from_at=stamp(start + timedelta(hours=3)),
                         to_at=stamp(start + timedelta(hours=3, minutes=2)))
            writer.event('stop', at=stamp(stop))
        finally:
            writer.close()

    start = now - timedelta(minutes=18)
    writer = EncryptedAgentStore(database, parent_key.public_key, 30)
    try:
        writer.event('start', at=stamp(start))
        writer.event('network_identity', at=stamp(start + timedelta(seconds=1)), identifier=HOME_ROUTER)
        writer.event('network_settings', at=stamp(start + timedelta(seconds=2)),
                     dns_observed=True, proxy_indicator=False, vpn_indicator=False)
        current = now - timedelta(minutes=12)
        finish = now - timedelta(minutes=7)
        while current <= finish:
            writer.event('tick', at=stamp(current), application=['Google Chrome', 'com.google.Chrome'])
            writer.event('website', at=stamp(current), domain='video.example')
            current += timedelta(seconds=15)
        writer.event('gap', at=stamp(now - timedelta(minutes=3)),
                     from_at=stamp(now - timedelta(minutes=5)),
                     to_at=stamp(now - timedelta(minutes=3)))
        writer.event('network', at=stamp(now - timedelta(minutes=1)), intervals=[
            [stamp(now - timedelta(minutes=1, seconds=15)), stamp(now - timedelta(minutes=1)),
             'en0', 3_820_000, 412_000]])
        writer.event('stop', at=stamp(now - timedelta(minutes=1)))
    finally:
        writer.close()


def prepare_profile(folder, with_report):
    server = ParentServer(folder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    if with_report:
        parent = PrivateKey.generate()
        key_vault.create_new(server.vault, key_vault.encrypt_private_key(
            parent, '638204'))
        server.private_key = parent
        server.backup_confirmed = True
        parent_settings.save_backup_confirmation(server.settings, True)
        synthetic_report(server.data, parent, datetime.now(UTC))
        network_labels.set_label(server.labels, parent, SCHOOL_ROUTER, 'school')
        network_labels.set_label(server.labels, parent, HOME_ROUTER, 'home')
        school_schedule.save(server.schedule, parent, {
            'timezone': 'Europe/Vienna', 'days': [0, 1, 2, 3, 4],
            'start': '08:30', 'end': '15:00',
        })
    thread.start()
    return server, thread


def capture(chrome, server, output, width, height):
    user_data = output.parent / (output.stem + '-chrome-profile')
    user_data.mkdir(mode=0o700)
    try:
        subprocess.run([
            chrome, '--headless=new', '--no-sandbox', '--disable-dev-shm-usage',
            '--hide-scrollbars', f'--user-data-dir={user_data}',
            f'--window-size={width},{height}', '--virtual-time-budget=10000',
            f'--screenshot={output}', server.url,
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45)
        if not output.is_file() or output.stat().st_size < 20_000:
            raise RuntimeError(f'Chrome did not create a complete screenshot: {output}')
    finally:
        shutil.rmtree(user_data, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', type=Path, default=Path('docs/assets'))
    parser.add_argument('--chrome', help='Chrome/Chromium executable; discovered on PATH by default')
    args = parser.parse_args()
    chrome = args.chrome or next((shutil.which(name) for name in (
        'google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser')
        if shutil.which(name)), None)
    if not chrome:
        parser.error('Chrome or Chromium was not found; pass --chrome')
    output = args.output_directory.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='family-activity-demo-capture-') as temporary:
        root = Path(temporary)
        empty_server, empty_thread = prepare_profile(root / 'empty-parent', False)
        try:
            capture(chrome, empty_server, output / 'parent-setup.png', 1440, 1280)
        finally:
            empty_server.shutdown()
            empty_thread.join(timeout=5)
            empty_server.server_close()

        report_server, report_thread = prepare_profile(root / 'report-parent', True)
        try:
            capture(chrome, report_server, output / 'parent-dashboard.png', 1440, 5000)
        finally:
            report_server.shutdown()
            report_thread.join(timeout=5)
            report_server.server_close()
    print(f'Captured the first-run parent PIN screen and fictional report screenshots in {output}')
    print('All keys, reports, server profiles, and browser profiles were temporary; no agent was started.')


if __name__ == '__main__':
    main()
