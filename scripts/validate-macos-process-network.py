#!/usr/bin/env python3
"""Verify macOS nettop byte deltas using repeated requests to example.com.

Only process names and sent/received byte totals are read from nettop; this
script does not save the request URL, response body, or any user activity.
"""
import subprocess
import sys
import time

from family_activity.process_network import MacProcessNetworkSampler


def validate():
    if sys.platform != 'darwin':
        raise RuntimeError('this validation must run on macOS')
    sampler = MacProcessNetworkSampler()
    try:
        probe = ('import time, urllib.request; '
                 '[(urllib.request.urlopen("https://example.com/", timeout=8).read(), time.sleep(1)) '
                 'for _ in range(6)]')
        result = subprocess.run([sys.executable, '-c', probe],
                                capture_output=True, text=True, timeout=20)
        if result.returncode:
            raise RuntimeError('the synthetic curl request failed: ' + result.stderr.strip())
        time.sleep(1.2)
        samples = sampler.drain()
        python_samples = [sample for sample in samples if sample.process == 'Python']
        received = sum(sample.received for sample in python_samples)
        sent = sum(sample.sent for sample in python_samples)
        if received <= 0 or sent <= 0:
            raise RuntimeError(f'nettop did not report the repeated synthetic request (received={received}, sent={sent})')
        return f'nettop measured synthetic Python traffic: {received} bytes received, {sent} bytes sent.'
    finally:
        sampler.close()


if __name__ == '__main__':
    try:
        print(validate())
    except Exception as error:
        print(f'Process network validation failed: {error}', file=sys.stderr)
        raise SystemExit(1)
