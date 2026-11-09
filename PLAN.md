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

The Apple-silicon app includes a native welcome/setup screen, visible menu-bar status, foreground-app sampling, network counters and settings, launchd restart, encrypted collection, parent dashboard, report sharing, retention, recovery, update restart, and removal.

**Evidence:** on macOS 26.6, 277 of 285 current-source tests passed and 8 host-specific checks were skipped. Real LaunchAgent setup, crash restart, update restart, removal, encrypted synthetic sampling, and gap recording passed. The 0.1.4 disk image and checksum were verified.

**Next:** build and publish the current Mac app; walk through setup and report return together on family Macs; review sleep/wake, local-network prompts, VoiceOver, recovery, update, and removal.

### 2. Windows family app — implementation and automated checks in place

The per-user installer, tray status, background startup, parent dashboard launcher, collection adapters, and report sharing are implemented. The latest hosted CI run passed all four Windows test groups and package checks.

**Next:** install and exercise the full setup, visible status, report handoff, update, recovery, and removal on a Windows computer. Keep Windows marked as not yet family-validated until that is done.

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
