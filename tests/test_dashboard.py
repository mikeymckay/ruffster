import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

class DashboardTests(unittest.TestCase):
    def test_new_parent_pin_uses_six_digit_validation_but_old_phrase_login_is_allowed(self):
        root = Path(__file__).parents[1] / 'family_activity' / 'parent_assets'
        html = (root / 'index.html').read_text()
        script = (root / 'app.js').read_text()
        self.assertIn("The child's computer can lock reports for you, but it cannot open them.", html)
        self.assertIn('If someone else gets your recovery copy, they may be able to guess the PIN', html)
        self.assertIn("Choose six digits your child doesn't know. Keep the recovery copy somewhere they can't access.", html)
        self.assertNotIn('separate public part', html)
        self.assertIn('pattern="[0-9]{6}" title="Enter six digits."', html)
        self.assertIn("$('password').pattern = '[0-9]{6}'", script)
        self.assertIn("$('password').removeAttribute('pattern')", script)
        self.assertIn('longer phrase from an older setup', script)
        self.assertIn("Choose six digits your child doesn't know. Keep the recovery copy somewhere they can't access.", script)
        self.assertNotIn('not strong protection if someone copies the recovery file', script)

    def test_report_handoff_waits_for_two_digits_and_sanitizes_input(self):
        root = Path(__file__).parents[1] / 'family_activity' / 'parent_assets'
        html = (root / 'index.html').read_text()
        script = (root / 'app.js').read_text()
        self.assertIn('Digits shown on the child\'s computer', html)
        self.assertIn('id="connect" type="button" disabled', html)
        self.assertIn("input.value.replace(/[^0-9]/g, '').slice(0, 2)", script)
        self.assertIn("!status.unlocked || !/^[0-9]{2}$/.test($('connection-code').value)", script)

    def test_report_explains_optional_child_side_browser_add_on(self):
        html = (Path(__file__).parents[1] / 'family_activity' / 'parent_assets' / 'index.html').read_text()
        self.assertIn("Website estimates are optional and experimental", html)
        self.assertIn("need a separate add-on on the child's computer", html)
        self.assertIn("not the parent's", html)
        self.assertIn("The Mac setup does not connect the add-on to the agent", html)
        self.assertIn("The add-on only sees supported browsers where it is installed", html)
        self.assertIn("pause or remove it, or use another browser", html)
        self.assertIn("It is not needed for the main app", html)
        self.assertIn("missing websites do not explain what happened", html)
        self.assertIn("domain names only, not full addresses or page contents", html)
        self.assertIn('id="website-status"', html)
        script = (Path(__file__).parents[1] / 'family_activity' / 'parent_assets' / 'app.js').read_text()
        self.assertIn('Website add-on observations: none in this report', script)
        self.assertIn('this report cannot tell which', script)
        self.assertIn('does not show complete browser coverage', script)

    def test_report_shows_measured_network_usage_per_interface_by_period(self):
        html = (Path(__file__).parents[1] / 'family_activity' / 'parent_assets' / 'index.html').read_text()
        script = (Path(__file__).parents[1] / 'family_activity' / 'parent_assets' / 'app.js').read_text()
        self.assertIn('Measured interface bytes', html)
        self.assertIn('interfaces can overlap', html)
        self.assertIn('Labels such as en0 are computer-generated connection IDs', html)
        self.assertIn('so no single total is shown', html)
        self.assertIn('cannot be attributed to individual websites or apps', html)
        self.assertIn('id="traffic-today"', html)
        self.assertIn('id="traffic-week-summary"', html)
        self.assertIn('Time zone for school hours', html)
        self.assertIn('id="zone-help"', html)
        self.assertIn('let localZone =', script)
        self.assertIn('local time zone where your child attends school', script)
        self.assertNotIn("resolvedOptions().timeZone || 'UTC'", script)
        self.assertIn("data.traffic_usage.today", script)
        self.assertIn("data.traffic_usage.week", script)
        self.assertIn("traffic-week-summary", script)
        self.assertIn('This does not show that traffic was zero.', script)
        self.assertIn('id="school-traffic"', html)
        self.assertIn('id="home-traffic"', html)
        self.assertIn('Estimated bytes', html)
        self.assertIn('data.traffic_contexts.school', script)
        self.assertIn('data.traffic_contexts.home', script)

    def test_parent_pairing_guidance_is_platform_neutral_and_cautious(self):
        assets = Path(__file__).parents[1] / 'family_activity' / 'parent_assets'
        html = (assets / 'index.html').read_text()
        script = (assets / 'app.js').read_text()
        self.assertIn('id="child-setup"', html)
        self.assertIn("On the child's computer, open Family Activity", html)
        self.assertIn('Windows setup and dashboard pairing are also experimental', html)
        self.assertIn('child computer', script)
        self.assertIn('operating-system settings the agent can inspect', script)
        self.assertIn('function formatUtcTimestamp(value)', script)
        self.assertIn("timeZone:'UTC'", script)
        self.assertIn("timeZoneName:'short'", script)
        self.assertIn('formatUtcTimestamp(data.recorded_through)', script)
        self.assertNotIn('These are indicators reported by macOS', script)

    def test_vpn_status_uses_plain_language_and_keeps_coverage_limit_visible(self):
        assets = Path(__file__).parents[1] / 'family_activity' / 'parent_assets'
        script = (assets / 'app.js').read_text()
        self.assertIn('VPN connection:', script)
        self.assertIn('a supported VPN connection appears active', script)
        self.assertIn('no built-in VPN connection appeared active', script)
        self.assertIn('could not check VPN status', script)
        self.assertIn('other VPN apps may not be detected', script)
        self.assertNotIn('VPN profile indicator', script)

    def test_rejects_untrusted_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.Popen([sys.executable, '-m', 'family_activity', 'dashboard', '--db', str(Path(tmp)/'db'), '--port', '0'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            try:
                url = proc.stdout.readline().strip().split(' ', 1)[1]
                with urllib.request.urlopen(url, timeout=3) as response:
                    self.assertEqual(response.status, 200)
                req = urllib.request.Request(url, headers={'Host': 'untrusted.example'})
                with self.assertRaises(urllib.error.HTTPError) as failure:
                    urllib.request.urlopen(req, timeout=3)
                self.assertEqual(failure.exception.code, 403)
                failure.exception.close()
            finally:
                proc.terminate()
                proc.wait(timeout=5)
                proc.stdout.close()

    def test_native_launcher_url_file_opens_loopback_and_stop_file_closes_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            url_file, stop_file = folder/'dashboard.url', folder/'stop-dashboard'
            proc = subprocess.Popen([sys.executable, '-m', 'family_activity', 'parent',
                                     '--data-dir', str(folder/'parent-data'), '--port', '0',
                                     '--no-browser', '--url-file', str(url_file), '--stop-file', str(stop_file)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 10
                while not url_file.exists() and proc.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(url_file.exists(), 'parent launcher URL was not published')
                url = url_file.read_text()
                self.assertTrue(url.startswith('http://127.0.0.1:'))
                with urllib.request.urlopen(url, timeout=3) as response:
                    self.assertEqual(response.status, 200)
                stop_file.write_text('stop')
                self.assertEqual(proc.wait(timeout=5), 0)
                self.assertFalse(url_file.exists())
            finally:
                if proc.poll() is None:
                    stop_file.write_text('stop')
                    try: proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.terminate(); proc.wait(timeout=5)
