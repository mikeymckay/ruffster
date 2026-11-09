from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit
import unittest

ROOT = Path(__file__).parents[1]
SITE = ROOT / 'docs'


class PageRefs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = set()
        self.images_without_alt = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.add(attrs['id'])
        for name in ('href', 'src'):
            if attrs.get(name):
                self.links.append((name, attrs[name]))
        if tag == 'img' and not attrs.get('alt'):
            self.images_without_alt.append(attrs.get('src', '<missing src>'))


class DocumentationSiteTests(unittest.TestCase):
    def test_github_pages_entry_points_and_assets_exist(self):
        for page in ('index.html', 'install.html', 'progress.html', 'faq.html', '404.html'):
            self.assertTrue((SITE / page).is_file(), page)
        self.assertTrue((SITE / '.nojekyll').is_file())
        self.assertTrue((SITE / 'assets/site.css').is_file())
        self.assertTrue((SITE / 'favicon.svg').is_file())
        self.assertTrue((SITE / 'assets/parent-setup.png').is_file())
        self.assertTrue((SITE / 'assets/parent-dashboard.png').is_file())

    def test_root_project_status_points_to_live_progress_report(self):
        status = (ROOT / 'PROJECT-STATUS.html').read_text(encoding='utf-8')
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        progress_url = 'https://mikeymckay.github.io/ruffster/progress.html'
        self.assertIn(progress_url, status)
        self.assertIn(progress_url, readme)
        self.assertNotIn('The Pages site is not live', status)

    def test_site_links_resolve_with_docs_as_the_site_root(self):
        failures = []
        pages = sorted(SITE.rglob('*.html'))
        parsed = {}
        for page in pages:
            refs = PageRefs()
            refs.feed(page.read_text(encoding='utf-8'))
            parsed[page] = refs
            if refs.images_without_alt:
                failures.append(f'{page.relative_to(ROOT)}: images missing alt text: {refs.images_without_alt}')
        # Resolving an HTML fragment may lazily add a target page below.
        # Iterate over a snapshot so this remains valid on newer Python versions.
        for page, refs in list(parsed.items()):
            for kind, value in refs.links:
                parts = urlsplit(value)
                if parts.scheme or parts.netloc:
                    continue
                target_text = unquote(parts.path)
                target = (page.parent / target_text).resolve() if target_text else page.resolve()
                if SITE.resolve() not in target.parents and target != SITE.resolve():
                    failures.append(f'{page.relative_to(ROOT)}: {value} escapes the Pages directory')
                    continue
                if target.is_dir():
                    target = target / 'index.html'
                if not target.is_file():
                    failures.append(f'{page.relative_to(ROOT)}: missing {value}')
                    continue
                if parts.fragment and target.suffix == '.html':
                    target_refs = parsed.get(target)
                    if target_refs is None:
                        target_refs = PageRefs()
                        target_refs.feed(target.read_text(encoding='utf-8'))
                        parsed[target] = target_refs
                    if parts.fragment not in target_refs.ids:
                        failures.append(f'{page.relative_to(ROOT)}: missing fragment #{parts.fragment} in {value}')
        self.assertEqual(failures, [])

    def test_readme_embeds_tracked_synthetic_screenshots(self):
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertIn('docs/assets/parent-setup.png', readme)
        self.assertIn('docs/assets/parent-dashboard.png', readme)
        self.assertIn('synthetic data only', readme)
        self.assertNotIn('artifacts/status-page/', readme)
        self.assertIn('## Delivery priorities', readme)
        self.assertIn('public project experience', readme)

    def test_parent_screenshots_have_a_temporary_synthetic_capture_tool(self):
        capture = (ROOT / 'scripts/capture-parent-demo-screenshots.py').read_text(encoding='utf-8')
        self.assertIn('TemporaryDirectory', capture)
        self.assertIn('video.example', capture)
        self.assertIn('no agent was started', capture)
        self.assertIn("'parent-setup.png'", capture)
        self.assertIn("'parent-dashboard.png'", capture)
        self.assertIn('recent home restart example', capture)
        self.assertIn("writer.event('heartbeat', at=stamp(finish))", capture)
        self.assertIn('restart coverage', (ROOT / 'README.md').read_text(encoding='utf-8'))

    def test_plan_prioritizes_mac_then_windows_and_public_parent_experience(self):
        plan = (ROOT / 'PLAN.md').read_text(encoding='utf-8')
        self.assertIn('### 1. Mac family app', plan)
        self.assertIn('### 2. Windows family app', plan)
        self.assertLess(plan.index('### 1. Mac family app'), plan.index('### 2. Windows family app'))
        self.assertIn('### 4. Public project and installation guide — live', plan)
        self.assertIn('source commit and checksum', plan)
        self.assertIn('family LAN', plan)
        self.assertNotIn('Pages source setting is still disabled', plan)

    def test_github_ci_covers_platforms_and_family_release_has_regular_release_path(self):
        workflow = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        project = (ROOT / 'native/windows/FamilyActivityStatus.csproj').read_text(encoding='utf-8')
        self.assertIn('os: [ubuntu-latest, macos-latest]', workflow)
        self.assertIn('windows-tests:', workflow)
        self.assertIn('windows-key-vault-check:', workflow)
        self.assertIn('timeout-minutes: 12', workflow)
        self.assertIn('run: python scripts/run-tests.py --files ${{ matrix.files }}', workflow)
        sharded_files = set()
        for line in workflow.splitlines():
            if line.strip().startswith('files:'):
                sharded_files.update(line.split(':', 1)[1].split())
        self.assertEqual(sharded_files | {'test_key_vault.py'},
                         {path.name for path in (ROOT / 'tests').glob('test_*.py')})
        self.assertIn('run: python scripts/run-tests.py --files test_key_vault.py', workflow)
        self.assertIn('windows-package-check', workflow)
        self.assertIn('-SkipLiveWindowsInstallCheck', workflow)
        self.assertIn('windows-bundle-extractor', workflow)
        self.assertIn('native/windows/bundle-extractor-tests/FamilyActivity.BundleExtractor.Tests.csproj', workflow)
        self.assertIn('macos-package-check', workflow)
        self.assertIn('scripts/validate-macos-install-flow.py', workflow)
        self.assertIn('cancel-obsolete-push-runs', workflow)
        self.assertIn('actions: write', workflow)
        self.assertIn('run.head_sha === context.sha', workflow)
        self.assertIn('timeout-minutes: 20', workflow)
        self.assertIn("dotnet-version: '10.0.x'", workflow)
        self.assertIn('<TargetFramework>net10.0-windows</TargetFramework>', project)
        self.assertNotIn('actions/upload-artifact', workflow)
        release = (ROOT / '.github/workflows/release-macos-unsigned-preview.yml').read_text(encoding='utf-8')
        release_notes = (ROOT / '.github/UNSIGNED-MAC-PREVIEW-RELEASE-NOTES.md').read_text(encoding='utf-8')
        family_release_notes = (ROOT / '.github/MAC-FAMILY-RELEASE-NOTES.md').read_text(encoding='utf-8')
        packager = (ROOT / 'scripts/package-macos-unsigned-preview.sh').read_text(encoding='utf-8')
        self.assertIn("'mac-preview-*'", release)
        self.assertIn("'mac-family-*'", release)
        self.assertIn('--prerelease', release)
        self.assertIn('.github/MAC-FAMILY-RELEASE-NOTES.md', release)
        self.assertIn('Ruffster for Mac 0.1.17', family_release_notes)
        self.assertIn('A real family setup and report exchange are the next validation step', family_release_notes)
        self.assertIn('scripts/run-tests.py', release)
        self.assertIn('shasum -a 256', packager)
        self.assertIn('hdiutil verify "$DMG"', packager)
        self.assertLess(packager.index('hdiutil create'), packager.index('hdiutil verify "$DMG"'))
        self.assertLess(packager.index('hdiutil verify "$DMG"'), packager.index('shasum -a 256'))
        self.assertIn('Source commit:', packager)
        self.assertIn('Open Anyway for Ruffster', packager)
        self.assertIn('approves Ruffster only', packager)
        self.assertIn('status --porcelain', packager)
        self.assertIn('must exactly match the checked-out HEAD', packager)
        self.assertIn('Ruffster helps parents and children understand everyday computer use together', release_notes)
        self.assertIn('Ruffster-Mac-Family-App-Apple-Silicon.dmg', release)
        self.assertIn('unsigned Apple-silicon family app', readme)
        self.assertIn('Mac family release', release)

    def test_test_runner_exposes_stall_diagnostics_in_github_summary(self):
        runner = (ROOT / 'scripts/run-tests.py').read_text(encoding='utf-8')
        self.assertIn('GITHUB_STEP_SUMMARY', runner)
        self.assertIn('dump_traceback_later(300, repeat=True', runner)
        self.assertIn('write_result_summary(summary_file, result)', runner)

    def test_accessibility_scan_is_pinned_and_runs_in_ci_without_site_runtime_deps(self):
        package = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))
        workflow = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
        script = (ROOT / 'scripts/validate-pages-accessibility.mjs').read_text(encoding='utf-8')
        self.assertEqual(set(package), {'name', 'private', 'scripts', 'devDependencies'})
        self.assertEqual(package['devDependencies'], {'axe-core': '4.14.0', 'ws': '8.22.2'})
        self.assertEqual(package['scripts']['check:pages-a11y'], 'node scripts/validate-pages-accessibility.mjs')
        self.assertIn('pages-accessibility', workflow)
        self.assertIn('Check website and parent UI accessibility', workflow)
        self.assertIn('npm ci', workflow)
        self.assertIn('npm run check:pages-a11y', workflow)
        for page in ('index.html', 'install.html', 'progress.html', 'faq.html'):
            self.assertIn(f"'{page}'", script)
        self.assertIn('wcag21aa', script)
        self.assertIn('horizontal overflow', script)
        self.assertIn('await waitForPageReady(send, target.name, target.path)', script)
        self.assertIn("name: 'parent dashboard setup'", script)
        self.assertIn("name: 'parent dashboard change parent PIN'", script)
        self.assertIn("name: 'parent dashboard report'", script)
        self.assertIn('restarts: 1', script)
        self.assertIn('has_key: unlocked, unlocked, has_report: hasReport, backup_confirmed: backupConfirmed', script)
        self.assertIn("details.open = true", script)
        self.assertIn('GITHUB_STEP_SUMMARY', script)
        self.assertIn('chromeVersion', script)
        self.assertIn('Axe violations | Horizontal overflow', script)
        self.assertIn("'.webp': 'image/webp'", script)

    def test_github_pages_guide_matches_published_repository_state(self):
        guide = (ROOT / 'GITHUB-PAGES.md').read_text(encoding='utf-8')
        self.assertIn('repository is public, and its Pages source is configured to use GitHub Actions', guide)
        self.assertIn('The live site and install guide are at <https://mikeymckay.github.io/ruffster/>', guide)
        self.assertIn('progress page', guide)
        self.assertIn('first-run setup and populated report screens', guide)
        self.assertIn('Both dashboard states use synthetic data only', guide)

    def test_local_reports_and_key_material_are_ignored_by_source_control(self):
        ignored = (ROOT / '.gitignore').read_text(encoding='utf-8').splitlines()
        for pattern in ('*.sqlite*', '*.db', '*.key', '*.vault', '*.pem', '*.p12', '*.pfx',
                        '.env', '.env.*', '!.env.example', '.DS_Store', '*.log', 'dist/'):
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, ignored)

    def test_platform_priority_and_release_caveat_are_visible(self):
        home = (SITE / 'index.html').read_text(encoding='utf-8')
        guide = (SITE / 'install.html').read_text(encoding='utf-8')
        self.assertIn('macOS comes first', home)
        self.assertIn('Linux is for development and testing', guide)
        self.assertIn('Ruffster for Mac is ready for families', guide)
        self.assertIn('This is Ruffster\'s first Mac family release', guide)
        self.assertIn('Drag Ruffster into the Applications folder', guide)
        self.assertIn('sign in to the child’s account before choosing', guide)
        self.assertIn('setup installs the background monitor just for the account signed in', guide)
        self.assertIn('Ruffster starts automatically whenever the child signs in', guide)
        self.assertIn('When does Ruffster run?', (SITE / 'faq.html').read_text(encoding='utf-8'))
        faq = (SITE / 'faq.html').read_text(encoding='utf-8')
        self.assertIn('Setup applies only to the account that is signed in when a parent confirms it', faq)
        self.assertIn('available for ongoing, visible use', faq)
        self.assertIn('adds each child\'s Mac one at a time', faq)
        self.assertIn('Why does my Mac ask me to confirm the first time?', faq)
        self.assertIn('Open parent dashboard', guide)
        self.assertIn('Set up this Mac together', guide)
        self.assertIn('background monitoring, a visible menu-bar status', guide)
        self.assertIn('https://github.com/mikeymckay/ruffster/releases/download/mac-family-0.1.17/Ruffster-Mac-Family-App-Apple-Silicon.dmg', guide)
        self.assertIn('https://github.com/mikeymckay/ruffster/releases/tag/mac-family-0.1.17', guide)
        self.assertIn('Open Anyway</strong> for Ruffster', guide)
        self.assertIn('your Mac’s general app protections stay on', guide)
        self.assertIn('Ruffster can stay in the shared Applications folder', guide)
        self.assertIn('It does not monitor the admin account or other family accounts', guide)
        self.assertIn('VoiceOver', guide)
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertIn('sign in to the child\'s account before setup, which installs monitoring for that account only', readme)
        self.assertIn('app can stay in the shared Applications folder', readme)
        self.assertIn('coarse expiry day beside each encrypted record; that day reveals roughly when it was recorded', readme)
        self.assertIn('exact event times stay encrypted for the parent', readme)
        faq = (SITE / 'faq.html').read_text(encoding='utf-8')
        self.assertIn('setup installs the background monitor for the signed-in account only', faq)
        self.assertIn('explicit screen-reader labels and help', readme)
        self.assertIn('actual VoiceOver behavior also need review', readme)

    def test_home_page_discloses_limits_of_optional_mac_process_totals(self):
        home = (SITE / 'index.html').read_text(encoding='utf-8')
        self.assertIn('optional experimental summary of bytes associated with processes', home)
        self.assertIn('Process totals may list helper services', home)
        self.assertIn('quick connections can be missed', home)

    def test_filtering_guidance_explains_network_scope_and_school_settings(self):
        faq = (SITE / 'faq.html').read_text(encoding='utf-8')
        dashboard = (ROOT / 'family_activity/parent_assets/index.html').read_text(encoding='utf-8')
        self.assertIn('home router', faq.lower())
        self.assertIn('school wi-fi', faq.lower())
        self.assertIn('hotspot', faq.lower())
        self.assertIn('school-hours schedule', dashboard.lower())

    def test_contextual_network_traffic_is_labeled_as_an_estimate(self):
        faq = (SITE / 'faq.html').read_text(encoding='utf-8')
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        dashboard = (ROOT / 'family_activity/parent_assets/index.html').read_text(encoding='utf-8')
        script = (ROOT / 'family_activity/parent_assets/app.js').read_text(encoding='utf-8')
        self.assertIn('estimate how much happened during the school schedule', faq)
        self.assertIn('do not confirm the computer\'s location', faq)
        self.assertIn('traffic', readme)
        self.assertIn('Estimated bytes', dashboard)
        self.assertIn('last observed router label', dashboard)
        self.assertIn('id="school-network-traffic"', dashboard)
        self.assertIn('id="other-network-traffic"', dashboard)
        self.assertIn("data.traffic_contexts.school_network", script)
        self.assertIn("data.traffic_contexts.other_network", script)

    def test_home_screenshot_caption_uses_light_background_text_color(self):
        css = (SITE / 'assets/site.css').read_text(encoding='utf-8')
        caption = css.split('.shot-caption {', 1)[1].split('}', 1)[0]
        self.assertIn('color:var(--muted)', caption)

    def test_mobile_preview_status_link_stays_inside_wrapped_navigation(self):
        css = (SITE / 'assets/site.css').read_text(encoding='utf-8')
        mobile = css.split('@media(max-width:620px)', 1)[1]
        nav_link = mobile.split('.nav .nav-cta {', 1)[1].split('}', 1)[0]
        self.assertIn('margin-left:auto', nav_link)

    def test_footer_brand_tagline_has_light_text_on_dark_background(self):
        css = (SITE / 'assets/site.css').read_text(encoding='utf-8')
        home = (SITE / 'index.html').read_text(encoding='utf-8')
        footer_brand = css.split('.footer .brand small {', 1)[1].split('}', 1)[0]
        self.assertIn('color:#c0d1c7', footer_brand)
        self.assertNotIn('aria-label="Ruffster home"', home)
        self.assertNotIn('aria-label="Open the full parent dashboard screenshot"', home)

    def test_mac_router_hint_is_disclosed_as_pseudonymous_not_location(self):
        faq = (SITE / 'faq.html').read_text(encoding='utf-8')
        native_setup = (ROOT / 'native/macos/setup.swift').read_text(encoding='utf-8')
        self.assertIn('simple DNS, proxy, and VPN indicators', faq)
        self.assertIn('The router hint is not a location', native_setup)

    def test_browser_extension_pause_and_data_limits_are_disclosed(self):
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        faq = (SITE / 'faq.html').read_text(encoding='utf-8')
        home = (SITE / 'index.html').read_text(encoding='utf-8')
        faq_text = ' '.join(faq.split())
        self.assertIn('on the child’s computer', home)
        self.assertIn('The main app needs no browser add-on', home)
        self.assertIn('not the parent’s', home)
        self.assertIn('not part of supported setup', home)
        self.assertIn('no add-on is needed on the parent\'s computer', readme)
        self.assertIn('turn it off or use another browser', readme)
        self.assertIn('never private-window domains or full URLs', readme)
        self.assertIn('Missing website details do not tell us why', readme)
        install = (SITE / 'install.html').read_text(encoding='utf-8')
        self.assertIn('browser add-on', faq)
        self.assertIn('optional experiment can share domain names', install)
        self.assertIn('not included in the Mac setup', install)
        self.assertIn('The child can pause it or use another browser', faq)
        self.assertIn('website details were not observed', faq)

    def test_privacy_and_childrens_rights_note_is_linked_and_clearly_scoped(self):
        privacy = (ROOT / 'PRIVACY-AND-CHILDREN.md').read_text(encoding='utf-8')
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        plan = (ROOT / 'PLAN.md').read_text(encoding='utf-8')
        self.assertIn('[Privacy and children\'s rights](PRIVACY-AND-CHILDREN.md)', readme)
        self.assertIn('review by qualified counsel is needed before broader distribution', readme)
        self.assertIn('not legal advice, a DPIA, or a claim', privacy)
        self.assertIn('Child\'s agency and rights', privacy)
        self.assertIn('Do not assume a household exemption applies', privacy)
        self.assertIn('Article 8 apply', privacy)
        self.assertIn('Article 35', privacy)
        self.assertIn('Charter of Fundamental Rights', privacy)
        self.assertIn('[PRIVACY-AND-CHILDREN.md](PRIVACY-AND-CHILDREN.md)', plan)

    def test_parent_key_explanation_avoids_cryptography_jargon(self):
        readme = (ROOT / 'family_activity/parent_assets/index.html').read_text(encoding='utf-8')
        guide = (SITE / 'install.html').read_text(encoding='utf-8')
        faq = (SITE / 'faq.html').read_text(encoding='utf-8')
        self.assertIn('Choose six numbers your child does not know', guide)
        self.assertIn('Your PIN opens the parent dashboard, and reports are encrypted for the parent computer', faq)
        self.assertNotIn('separate public part', readme + guide + faq)

    def test_parent_access_and_pairing_copy_is_plain_and_honest_about_preview_codes(self):
        dashboard = (ROOT / 'family_activity/parent_assets/index.html').read_text(encoding='utf-8')
        script = (ROOT / 'family_activity/parent_assets/app.js').read_text(encoding='utf-8')
        product = (ROOT / 'PRODUCT-DESIGN.md').read_text(encoding='utf-8')
        self.assertIn('Your parent access PIN', dashboard)
        self.assertIn('six-digit PIN your child doesn\'t know', dashboard)
        self.assertIn('Repeat these steps for each child\'s Mac', dashboard)
        self.assertIn('Show two digits', dashboard)
        self.assertIn('Download connection file', dashboard)
        self.assertIn('Download recovery copy', dashboard)
        self.assertNotIn('Download public key', dashboard)
        self.assertNotIn('Download encrypted key backup', dashboard)
        self.assertIn('the sender shows two digits, and the receiver enters them', product)
        self.assertIn('digits only find the nearby computer', product)
        install = (SITE / 'install.html').read_text(encoding='utf-8')
        faq = (SITE / 'faq.html').read_text(encoding='utf-8')
        self.assertIn('Pair each Mac with the parent Mac', install)
        self.assertIn('allow Local Network access', install)
        self.assertIn('save an encrypted report file from the child\'s status menu', install)
        self.assertIn('open it in the parent\'s dashboard', install)
        self.assertIn('download the connection file from the parent dashboard', install)
        self.assertIn('Choose connection file…', install)
        self.assertIn('This is different from the recovery copy', install)
        self.assertIn('Both computers need to be on the same Wi-Fi', faq)
        self.assertIn('allow Local Network access', faq)
        self.assertIn('Set up parent access', script)
        self.assertIn('exactly six digits', script)

    def test_two_digit_handoff_uses_the_same_simple_pattern_in_both_directions(self):
        root = ROOT
        dashboard = (root / 'family_activity/parent_assets/index.html').read_text(encoding='utf-8')
        mac_status = (root / 'native/macos/status.swift').read_text(encoding='utf-8')
        windows_status = (root / 'native/windows/Program.cs').read_text(encoding='utf-8')
        faq = (SITE / 'faq.html').read_text(encoding='utf-8')
        self.assertIn('the sender shows two digits and the receiver enters them', faq)
        self.assertIn('Repeat these steps for each child\'s Mac', dashboard)
        self.assertIn('It will show two digits. Enter them here.', dashboard)
        self.assertIn('Show these two digits to your parent', mac_status)
        self.assertIn('Show these two digits to your parent', windows_status)

    def test_windows_guide_matches_two_digit_handoff_and_current_package_limits(self):
        windows = (ROOT / 'WINDOWS.md').read_text(encoding='utf-8')
        self.assertIn('parent computer shows two digits and the child computer enters them', windows)
        self.assertIn('digits only find the nearby computer', windows)
        self.assertIn('self-contained installer', windows)
        self.assertIn('changes to “Monitoring is paused” when samples are overdue', windows)
        self.assertIn('If the tray helper or its heartbeat channel stops, the agent exits', windows)
        self.assertIn('RuffsterSetup.exe', windows)
        self.assertIn('Save an encrypted report file', windows)
        self.assertIn('does not use the local network', windows)
        self.assertIn('copies it into the signed-in user’s Local AppData folder', windows)
        self.assertNotIn("five-minute one-use setup code", windows)

    def test_pages_deployment_is_main_only_and_uploads_docs(self):
        workflow = (ROOT / '.github/workflows/pages.yml').read_text(encoding='utf-8')
        self.assertIn('push:', workflow)
        self.assertIn("      - 'docs/**'", workflow)
        self.assertIn('workflow_dispatch:', workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertIn('npm run check:pages-a11y', workflow)
        self.assertIn("path: docs", workflow)
        self.assertIn('actions/checkout@v4', workflow)
        self.assertIn('contents: read', workflow)
        self.assertIn("uses: actions/deploy-pages@v4", workflow)
        self.assertIn("uses: actions/upload-pages-artifact@v3", workflow)
        self.assertNotIn('pull_request:', workflow)

    def test_mac_status_state_self_check_runs_during_native_bundle_build(self):
        native_status = (ROOT / 'native/macos/status.swift').read_text(encoding='utf-8')
        builder = (ROOT / 'scripts/build-macos-preview.sh').read_text(encoding='utf-8')
        self.assertIn('case starting', native_status)
        self.assertIn('case active', native_status)
        self.assertIn('case paused', native_status)
        self.assertIn('--self-test-state', native_status)
        self.assertIn('Monitoring On', native_status)
        self.assertIn('Monitoring Paused', native_status)
        self.assertIn('setAccessibilityLabel', native_status)
        self.assertIn('setAccessibilityHelp', native_status)
        self.assertIn('Ruffster recently saved a sample', native_status)
        self.assertIn('Some time may be missing from the report; let your parent know', native_status)
        self.assertNotIn('Ruffster experimental monitoring', native_status)
        self.assertNotIn('Ask your parent or guardian about this test', native_status)
        self.assertIn('maximumSampleInterval = 3600.0', native_status)
        self.assertIn('MonitoringState.sampleInterval(from:', native_status)
        self.assertIn('hugeIntervalHeartbeat == .paused', native_status)
        self.assertIn('Monitoring status self-check failed:', native_status)
        self.assertIn('helpers/status" --self-test-state', builder)
        self.assertIn('NSLocalNetworkUsageDescription', builder)
        self.assertIn('connect a parent computer or send an encrypted report', builder)
        launchd = (ROOT / 'family_activity/macos_launchd.py').read_text(encoding='utf-8')
        self.assertIn('AssociatedBundleIdentifiers', launchd)

    def test_macos_package_runs_frozen_parent_dashboard_smoke_check(self):
        builder = (ROOT / 'scripts/build-macos-preview.sh').read_text(encoding='utf-8')
        smoke = (ROOT / 'scripts/validate-macos-preview-bundle.py').read_text(encoding='utf-8')
        workflow = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
        self.assertIn('validate-macos-preview-bundle.py', builder)
        self.assertIn("'--check-bundle'", smoke)
        self.assertIn("'agent', 'share', 'export-report'", smoke)
        self.assertIn("'parent', '--no-browser'", smoke)
        self.assertIn("status.status != 403", smoke)
        self.assertIn("'export-report', '--db'", smoke)
        self.assertIn('PREVIEW_FILE_RETURN_SAMPLE', smoke)
        self.assertIn('encrypted file export/import round-trip passed', smoke)
        self.assertIn('macos-package-check:', workflow)
        self.assertIn('build-macos-preview.sh', workflow)

    def test_windows_package_runs_frozen_parent_dashboard_smoke_check(self):
        builder = (ROOT / 'scripts/build-windows-preview.ps1').read_text(encoding='utf-8')
        smoke = (ROOT / 'scripts/validate-windows-preview-bundle.py').read_text(encoding='utf-8')
        guide = (ROOT / 'WINDOWS.md').read_text(encoding='utf-8')
        self.assertIn('validate-windows-preview-bundle.py', builder)
        self.assertIn("'agent', 'share', 'export-report'", smoke)
        self.assertIn("'parent', '--no-browser'", smoke)
        self.assertIn("'--url-file'", smoke)
        self.assertIn("'--stop-file'", smoke)
        self.assertIn('status.status != 403', smoke)
        self.assertIn("'export-report', '--db'", smoke)
        self.assertIn('PREVIEW_FILE_RETURN_SAMPLE', smoke)
        self.assertIn('Windows named-event heartbeat passed.', smoke)
        self.assertIn("if os.name != 'nt':", smoke)
        self.assertIn('--self-test-status-ipc', smoke)
        self.assertIn('Europe/Vienna', smoke)
        self.assertIn('--collect-all tzdata', builder)
        self.assertIn('--self-test-ui', builder)
        self.assertIn('constructs and lays out the first-run and removal forms', guide)
        self.assertIn('renders a report using that time zone', guide)
        self.assertIn('temporarily registers the actual per-user task', guide)
        self.assertIn('do not install on a family computer or exercise the visible controls interactively', guide)

    def test_macos_candidate_packaging_is_gated_and_documented(self):
        script = (ROOT / 'scripts/package-macos-candidate.sh').read_text(encoding='utf-8')
        lifecycle_check = (ROOT / 'scripts/validate-macos-install-flow.py').read_text(encoding='utf-8')
        guide = (ROOT / 'MACOS-DISTRIBUTION.md').read_text(encoding='utf-8')
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        status = (ROOT / 'PROJECT-STATUS.html').read_text(encoding='utf-8')
        self.assertIn('Developer ID Application:', script)
        self.assertIn('security find-identity', script)
        self.assertIn('--options runtime --timestamp', script)
        self.assertIn('notarytool submit', script)
        self.assertIn('stapler validate', script)
        self.assertIn('not approved for family deployment', script)
        self.assertIn('MACOS-DISTRIBUTION.md', readme)
        self.assertIn('no valid code-signing identities', guide)
        self.assertIn('FAMILY_ACTIVITY_VERSION=\'0.1.0\'', guide)
        self.assertIn('macos_install.install', lifecycle_check)
        self.assertIn('readiness_check=lambda database, previous_count: True', lifecycle_check)
        self.assertIn('macos_install.uninstall', lifecycle_check)
        self.assertIn("_launchctl('kill', 'SIGKILL'", lifecycle_check)
        self.assertIn('exec /bin/sleep 60', lifecycle_check)
        self.assertIn('validate-macos-install-flow.py', guide)
        self.assertIn('https://mikeymckay.github.io/ruffster/progress.html', status)

    def test_progress_page_reports_current_family_release_and_validation_gates(self):
        status = (SITE / 'progress.html').read_text(encoding='utf-8')
        self.assertIn('Ruffster for Mac 0.1.17 is available for families', status)
        self.assertIn('What we’re improving next', status)
        self.assertIn('Download Ruffster for Mac 0.1.17', status)
        self.assertIn('Mac-to-Mac setup and the first family report review are still to try together', status)
        self.assertIn('the published parent dashboard opened a synthetic encrypted report', status)
        self.assertIn('Mac parent key sharing worked over the home LAN with a synthetic client', status)
        self.assertIn('the packaged Mac client completed a same-Mac key handoff', status)
        self.assertIn('These checks do not replace Mac-to-Mac setup', status)
        self.assertIn('300 tests: 295 passed and five platform/tool checks were skipped', status)
        self.assertIn('synthetic first-run, PIN-change, and populated parent-dashboard screens', status)
        self.assertIn('zero Axe violations and no horizontal overflow', status)
        self.assertIn('<h2>Current automated test results</h2>', status)
        self.assertIn('300 tests ran on the Linux development host: 295 passed', status)
        self.assertIn('first-run parent dashboard, PIN-change form, and populated parent report', status)
        self.assertNotIn('293 tests', status)
        self.assertIn('the real Windows agent lifecycle still needs a logged-in Windows computer', status)
        self.assertIn('cannot verify an interactive Task Scheduler session', status)

    def test_product_design_matches_unsigned_mac_release_and_family_install_state(self):
        design = (ROOT / 'PRODUCT-DESIGN.md').read_text(encoding='utf-8')
        self.assertIn('installed in `/Applications` on the first family Mac', design)
        self.assertIn('guided setup was not opened, so no agent was installed or started', design)
        self.assertIn("currently ships unsigned with clear first-open instructions", design)
        self.assertIn('not prerequisites for family testing', design)
