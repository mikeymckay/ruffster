# Ruffster implementation plan

Ruffster helps parents and children understand computer use together, especially during school hours. Monitoring stays visible, parents choose what to collect and how long to keep it, and reports are a starting point for family conversations.

## Product decisions

- Build and validate macOS first, then Windows. Linux is a development and test host, not a student platform.
- Keep the first version local-first. Pair and transfer reports directly over a family LAN; keep encrypted file transfer as the fallback. A future rendezvous service may help devices find each other, but will not carry report data. Consider compression only if a later data-relay service needs it.
- Keep the parent access PIN and recovery copy on the parent computer. Child computers receive only what they need to encrypt reports. Use short-lived two-digit pairing prompts to find a nearby computer.
- Do not promise website traffic attribution. The standard Mac setup does not include a browser extension. Interface totals are measured; optional per-process totals are approximate and do not identify websites.
- No Apple Developer ID is available. Keep the Mac download clearly labeled as unsigned, publish the source commit and checksum, link Apple's first-open instructions, and never change Gatekeeper settings. Signing can be added if an identity becomes available; it is not a prerequisite for useful family testing.

## Milestones

### 1. Mac family app — core implemented; family setup still to validate

The Apple-silicon app includes a native welcome/setup screen, visible menu-bar status, foreground-app sampling, network counters and settings, launchd restart, encrypted collection, parent dashboard, report sharing, retention, recovery, update restart, and removal. The dashboard records runtime, gaps, and starts after a session without a stop record; it explains that the cause is unknown. Setup now waits for launchd to keep the agent alive and save a fresh encrypted sample before confirming that monitoring is ready. If nearby-computer pairing fails, the Mac setup screen offers a retry or connection-file choice and explains the local-network permission. Pairing also reopens cleanly after a one-use transfer; its Windows UDP port avoids the OS dynamic-port range.

**Evidence:** the latest local suite ran 297 tests: 292 passed and 5 host-specific checks were skipped. Real LaunchAgent setup, crash restart, update restart, removal, encrypted synthetic sampling, and gap recording passed. The Mac family release 0.1.12 passed hosted workflow `42568960066`; its DMG SHA-256 is `e3bee2b071ac707e9122497df569ad091429e1df7071d019e1de267e6687ad59`. On the test Mac, `hdiutil verify` confirmed the published disk image is valid. The preceding 0.1.11 release passed hosted workflow `42562547418`, including the full Mac test suite and app packaging; general CI run `42562547391` passed. On the test Mac (macOS 26.6, Apple silicon), the published disk image matched its sidecar (`2353b9f4473329a8e7d6953b869b44cb57f9990511104109126ec15531d2908d`), `hdiutil verify` passed, and the read-only mounted app reported version `0.1.11`, bundle ID `org.ruffster.app`, and the detailed first-open instructions. The bundle check, status-helper self-check, welcome-layout self-check, and frozen-core help check all passed on that Mac without installing or starting an agent. Pages deployment `42562543942` succeeded. On 2026-11-09, the Mac app successfully shared a synthetic encrypted report over the home LAN to a temporary parent dashboard; the received record decrypted correctly while the saved database remained ciphertext. The run used no family activity and no monitoring service. A Mac-initiated connection to the Linux test host failed, so Mac-to-Mac pairing remains unverified; the install guide now explains the connection-file fallback. At that stage Ruffster had not yet been installed; the subsequent installation is recorded below. Commit `7808f590` passed hosted CI workflow `42568550067`, including the real disposable LaunchAgent startup/restart/removal check and Mac and Windows package smoke builds. Release workflow `42568960066` built and published Mac 0.1.12; Pages deployment `42568281943` published the install guide with the new version and setup-readiness steps. Windows CI then exposed a reserved dynamic UDP port and a cleanup race when restarting a one-use pairing session. Port 39372 and an orderly old-session join fixed both; the restart regression passed locally and all Windows test shards passed in CI `42570779319`. Release `mac-family-0.1.13` passed workflow `42571171838`; its SHA-256 matched (`6f36fb6dd1ac320b56a1e15249d6dba7e0101662fdf35f8db41f231b0dc1812c`) and the read-only package, status, and setup layout checks passed on the test Mac. The shutdown-test tolerance fix passed hosted workflow `42573738899` across Linux, macOS, all Windows test groups, and both preview package smoke builds. Pages accessibility passed in `42573738868`. No monitoring agent was installed or run. For commit `8ffb504`, the complete local suite passed (294 tests, 5 skipped), the four public Pages and two synthetic parent dashboard states passed desktop/mobile accessibility checks, the Pages deployment succeeded, and hosted CI `42587923902` passed all Linux, macOS, Windows, and package build jobs. SSH and Tailscale report the family Mac offline, so Annika's account setup and real family data remain pending.

The Mac welcome and confirmation screens now state that setup monitors only the signed-in account, and the install guide, FAQ, and README tell families to sign in to the child's account first. Source checks, the Pages accessibility scan, and hosted Mac build/test run `42576369127` passed. The account-scope clarification has not been reviewed interactively on the family Mac. On 2026-11-09, the published 0.1.14 app was installed in `/Applications/Ruffster.app` from the checksum-verified release. The app's bundle, status helper, welcome layout, and frozen-core checks passed. The setup window was not opened, no LaunchAgent was installed, and no family activity was collected. The Mac later went to sleep and SSH timed out; live setup, pairing, and the first report still need a family session.

Mac family release 0.1.14 is published from commit `89bcb1f`. Release workflow `42578080858` passed the Mac suite and packaged the Apple-silicon DMG; its SHA-256 matched the release sidecar. Main CI `42582684276` passed all Linux, macOS, Windows, and package smoke checks after the Windows pairing-test timeout adjustment. Pages deployment `42582684262` published the updated first-family-Mac progress. The app is installed but first-run disclosure, parent-key pairing, and real report return remain unverified.

**Next:** complete visible setup from the intended child account and parent dashboard, then inspect the first encrypted report together. Keep the Mac awake during hands-on SSH validation with a temporary power assertion while plugged in. Review sleep/wake gaps, local-network prompts, VoiceOver, recovery, update, and removal.

### 2. Windows family app — implementation and automated checks in place

The per-user installer, tray status, background startup, parent dashboard launcher, collection adapters, and report sharing are implemented. The Windows package build and unit tests run in hosted CI; it intentionally skips the live Task Scheduler lifecycle because the runner lacks the interactive session required by the per-user task. An attempt to run that lifecycle on the hosted runner timed out; the synthetic lifecycle remains available for a logged-in Windows session. The actual setup, tray, and family report flow still need hands-on Windows review.

**Next:** review the full setup, visible tray status, report handoff, recovery, and removal on a Windows computer; keep family usability marked unverified until then. Keep Windows marked as not yet family-validated until that is done.

### 3. Family reports and guidance — implemented; learn from real use

The local dashboard shows daily and weekly summaries, schedule-based school hours, family-labeled networks, coverage gaps, retention, device-separated reports, filtering indicators, and clear notes about estimates and missing observations. It does not block apps or treat a configuration change as proof of misconduct.

**Next:** review the first family reports together and improve the explanations, default retention, and recovery steps from that experience. Keep website categories and process-level traffic estimates clearly labeled and optional.

### 4. Public project and installation guide — live

The README and GitHub Pages site include a home page, install guide, progress page, FAQ, and synthetic setup/report screenshots. Pages deploys from GitHub Actions after the desktop/mobile accessibility scan passes.

**Next:** keep download and readiness copy current, review the native Mac screens with VoiceOver and a nontechnical parent, and keep screenshot examples in sync with the app.

### 5. Family release readiness — open

Before describing Ruffster as a supported family release, complete hands-on Mac use, Windows computer review, parent/child usability sessions, accessibility review, privacy and children's-rights review, and checks for recovery, retention, deletion, upgrades, and uninstall. Keep the unsigned Mac first-open steps honest and preserve the operating system's protections.

## Working practices

- Ship small changes with automated tests and record the platform and data used for real-device checks in [VALIDATION.md](VALIDATION.md).
- Use synthetic records for development, screenshots, and automated checks. Do not add screenshots, keystrokes, message contents, audio, or camera collection.
- Keep known limitations in [PRODUCT-DESIGN.md](PRODUCT-DESIGN.md), collection details in [PRIVACY-AND-CHILDREN.md](PRIVACY-AND-CHILDREN.md), and contributor conventions in [AGENTS.md](AGENTS.md).
- Validate platform behavior on that operating system. Linux test results do not establish macOS or Windows behavior.
