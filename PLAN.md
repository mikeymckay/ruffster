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

**Current evidence:** Mac 0.1.17 is the published Apple-silicon family app. Its tag workflow `42603995365` passed the full Mac tests, ad-hoc bundle seal and strict signature verification, and packaged dashboard/report smoke checks. Main CI `42604919892` passed Linux, macOS, all Windows groups, and both package builds. The release DMG matched its SHA-256 sidecar. A synthetic Mac-to-parent report transfer and real disposable LaunchAgent lifecycle have been validated on the test Mac; no family activity was used. On Annika's Mac, SSH previously confirmed the separate `annikamckay` account and an older Ruffster app in shared Applications. Version 0.1.16 was staged for that Mac, but SSH dropped while its signature was being updated; version 0.1.17 has not been verified or opened there. No child-account LaunchAgent, parent pairing, or family report is confirmed. Historical package and test records are in [VALIDATION.md](VALIDATION.md).

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

## Latest shipped step — 2026-11-09

Mac 0.1.17 is published. It includes the app bundle's local ad-hoc resource seal and strict signature verification, alongside the existing parent PIN change, monitoring runtime, gap, and restart summary. Local validation passed 300 tests with five host-specific skips; desktop and phone accessibility scans found zero Axe violations. Main CI `42603935608` passed Linux, macOS, Windows, and package checks. Tag release workflow `42603995365` passed its Mac tests and package smoke checks. The published DMG SHA-256 (`d1dea86ee367a3e7665c64dc5b5ee6a4cd6898f3c0be0b700b17ab0f1c5c2162`) matches its release sidecar. Annika's Mac was reachable briefly and the 0.1.16 app was staged in `/Users/Shared/Ruffster.app`; SSH dropped while checking an updated signature, so the staged copy's final state is unknown and 0.1.17 has not been installed for her account. Her per-account setup, parent-key pairing, and real school-day collection remain unverified; no monitoring is known to be running and no family activity has been collected.
