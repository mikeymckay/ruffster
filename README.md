# Family Activity

**Make computer use easier to talk about.** Family Activity is an open-source prototype for parents and children to review computer use together, with visible monitoring, local reports, and explicit limits on what the data can tell you.

**This is not ready for family deployment.** The Mac package is unsigned. Windows has not been tested on a Windows computer. Setup, accessibility, security, key recovery, and family usability still need validation. There is no supported release download.

[Website source (Pages-ready)](docs/index.html) · [Getting started](docs/install.html) · [FAQ](docs/faq.html) · [Privacy and children's rights](PRIVACY-AND-CHILDREN.md) · [Implementation plan](PLAN.md) · [Current status](PROJECT-STATUS.html)

> **Platform priority:** macOS first, then Windows. Linux is a development and test host only; Linux is not a student-facing target in the current scope.

## A look at the prototype

These full-page captures show the local parent dashboard's first-run PIN setup and a sample report. The report uses synthetic data only; no child's activity appears in these images. Select either image to view it at full size.

<p align="center">
  <a href="docs/assets/parent-setup.png"><img src="docs/assets/parent-setup.png" alt="Parent dashboard showing the first-run parent PIN setup" width="38%"></a>
  &nbsp;
  <a href="docs/assets/parent-dashboard.png"><img src="docs/assets/parent-dashboard.png" alt="Full-page synthetic report with coverage gaps, schedule-based school-hour estimates, family-labeled home, school, and other network views, and measurement limits" width="58%"></a>
</p>

<p align="center"><sub>First-run parent PIN setup · synthetic report with measurement notes</sub></p>

## Product principles

- **Visible, disclosed monitoring.** The computer user should be able to see when the agent is active and understand what it collects.
- **Conversation, not control.** The app does not block applications or score a child's behavior.
- **Local by default.** The child agent encrypts each observation to a public key supplied by the parent. The matching private key stays with the parent.
- **Careful language.** Estimates remain estimates. Missing observations, unfamiliar networks, and configuration indicators are not evidence of intent.
- **Minimal collection.** No screenshots, keystrokes, audio, camera, message contents, or full website URLs.

## What the prototype can show

| Observation | Current behavior | Limit |
| --- | --- | --- |
| Foreground application | Sampled application name | Time between matching samples is only an estimate and may include idle time. |
| Network traffic | Today and past-seven-day sums of recorded byte-counter changes per interface, plus estimated school-hour and Home-, School-, and Other-labeled network breakdowns | Schedule estimates apportion interval bytes by the chosen hours; network estimates use the last observed parent-labeled router. Interfaces can overlap, missed intervals may be uncounted, and totals cannot be attributed to websites or applications. |
| Monitoring coverage | Sessions, heartbeats, and observable gaps; the Mac menu-bar and Windows tray companions show starting, recent-sample, and overdue states from completed encrypted samples. The Mac helper exposes explicit screen-reader labels and help. | A gap does not establish whether the cause was sleep, a crash, permissions, removal, or something else. The Windows indicator has not run on Windows; the rendered Mac menu item and actual VoiceOver behavior still need interactive review. |
| Network changes | Mac setup records a pseudonymous hint when the default router changes; the experimental Windows preview is wired to do the same. The raw router address is not saved. | Windows PowerShell behavior has not been verified on a Windows computer. A router hint is not proof of location, and router detection can be unavailable. |
| DNS and proxy configuration | Reduced true/false/unknown indicators | These indicators are incomplete and cannot confirm that filtering works. Windows VPN status remains unknown. |
| Website domains | Optional experimental Chromium extension installed on the child's computer; the parent report shows how many domain samples arrived and when the latest one was recorded. | It runs inside a supported browser, so the child can disable it or switch browsers. It is not complete website monitoring and is not integrated into the Mac setup or available as a supported family install. It sends domain names only, never inspects private-window domains, and has a visible pause control. A report with no domains cannot identify why observations are missing. |

The school-hours view uses a schedule chosen by the parent; it does not prove that the computer was at school. Home-, School-, and Other-labeled network views use family labels on router hints; they can be wrong or unavailable. The School-labeled network view is separate from the schedule-based school-hours view, and the estimates can overlap.

## Privacy and encryption

The encrypted agent stores ciphertext and coarse retention metadata in a local SQLite database. Parent setup uses a six-digit PIN the child should not know. The child's computer can lock reports for you, but it cannot open them. Keep the encrypted recovery copy somewhere the child cannot access; use it with your PIN if you move to a new parent computer. The handoff uses one simple pattern in either direction: the sending computer shows two digits, and the receiving computer enters them. The digits only find a nearby computer; they are not a password. The transfer is encrypted, requires both devices on the same local network, and has not been validated on supported Mac or Windows machines. No cloud account is required.

Encryption does not hide every detail: record counts, ordering, approximate record-size buckets, expiry days, file growth, and filesystem timestamps remain visible. Observation plaintext exists in the agent's memory before encryption. A person with administrator access to the child computer can inspect or change the agent. The prototype is not tamper-proof and has not received an independent security review. If the parent loses every usable encrypted recovery copy and forgets their PIN, the encrypted reports cannot be opened. Recovery files created by older versions can still be restored with their original longer passphrase.

The monitoring agent now refuses to start without the parent's public key and writes activity only as encrypted records. Earlier prototype databases and low-level test utilities may contain plaintext; they are not automatically migrated or erased. The dashboard can still open an older local plaintext database, so check existing files before sharing or retaining them. For a supported old prototype schema, the developer CLI can create an encrypted copy while leaving the source untouched:

```sh
python -m family_activity encrypt-legacy \
  --source /path/to/old-activity.sqlite3 \
  --public-key /path/to/family-public.key \
  --output /path/to/activity-encrypted.sqlite3 \
  --retention-days 30
```

The command applies retention to original event times and omits expired rows. Verify the new file before manually deciding what to do with the plaintext source; secure erasure is not guaranteed. Encrypted collection and parent setup remain experimental and are not a supported family release.

See [ENCRYPTION.md](ENCRYPTION.md) for the threat model and known limitations, and [AGENTS.md](AGENTS.md) for development rules.

The engineering requirements and open European privacy and children's-rights questions are recorded in [PRIVACY-AND-CHILDREN.md](PRIVACY-AND-CHILDREN.md). This is not a legal compliance determination; review by qualified counsel is required before family release.

## Delivery priorities

1. **Make macOS dependable first.** Validate setup and removal, visible status, sleep/wake, permissions, user changes, restart recovery, encrypted reports, and key recovery on real Macs. Finish a parent-friendly signed and notarized installer before family distribution.
2. **Port the finished family flow to Windows.** Test installation, startup and recovery, visible tray status, network and app observations, encrypted report handoff, parent dashboard, updates, and removal on real Windows computers.
3. **Make the public project experience excellent.** Keep this README useful to a parent arriving for the first time and to a contributor; publish a polished GitHub Pages home page, family installation guide, and plain-language FAQ. Include current synthetic screenshots, clear readiness status, accessible responsive layouts, and no download link until a supported release exists.
4. **Validate with families and reviewers.** Observe nontechnical parents and children using the whole flow; complete accessibility, security, privacy, and European children's rights reviews.

Linux remains a low-priority development and test host. It is not a student-facing platform target. The task list and release gates are in [PLAN.md](PLAN.md); the Pages design and launch checklist is in [GITHUB-PAGES.md](GITHUB-PAGES.md).

See the full [implementation plan](PLAN.md). Website source is in [`docs/`](docs/), and [GITHUB-PAGES.md](GITHUB-PAGES.md) explains the intended deployment.

## Developer quick start

Use Python 3.10 or newer. Linux is useful for running the shared tests, but test success on Linux is not evidence that macOS or Windows behavior works.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m unittest discover -s tests -v
node --check family_activity/parent_assets/app.js
```

For local UI development, start the experimental parent app:

```sh
.venv/bin/python -m family_activity parent
```

It binds to loopback. The default CLI database and dashboard are developer tools, not a family installation path. Do not expose them to a network.

GitHub Actions is configured to run the test suite on Linux, macOS, and Windows, then build the Mac and Windows previews on their native runners. The Mac job also exercises the harmless per-user LaunchAgent startup/restart/removal path with a sleep-only fixture. Generated previews are discarded; CI does not publish install downloads. These hosted checks will begin after this project is pushed to GitHub.

### Build experimental previews

**macOS (Apple silicon):** build on a Mac with the project dependencies and PyInstaller installed. This makes an unsigned development bundle, not a supported installer. The builder compiles the native helpers and smoke-checks the frozen commands and loopback parent dashboard without installing monitoring. A private Developer ID signing and notarization path for a preview drag-to-Applications disk image is documented in [MACOS-DISTRIBUTION.md](MACOS-DISTRIBUTION.md); it is unverified because this project has no signing identity yet.

```sh
.venv/bin/python -m pip install -e ".[build]"
./scripts/build-macos-preview.sh "$(pwd)/.venv/bin/python" "$(pwd)/dist/family-activity-preview"
```

**Windows x64:** build on Windows with Python and the .NET 10 LTS SDK. The builder has not yet run on a Windows machine.

```powershell
python -m pip install -e ".[build]"
.\scripts\build-windows-preview.ps1 -OutputDirectory .\dist\FamilyActivityPreview
```

Read [WINDOWS.md](WINDOWS.md) before working on the Windows preview. A Linux cross-compile checks the C# source only; it cannot validate Windows installation or runtime behavior.

## Project website

The static website source in `docs/` contains the home page, getting-started guide, FAQ, and screenshots. It has no external runtime dependencies and is intended to publish from the repository's `/docs` folder with GitHub Pages. See [GITHUB-PAGES.md](GITHUB-PAGES.md). The website should not link to a family download until a supported signed release exists.

Refresh the synthetic parent setup and report screenshots with `.venv/bin/python scripts/capture-parent-demo-screenshots.py` (Chrome or Chromium required). The first-run image has no parent key; the report image uses a temporary key and fictional activity records. The tool starts no monitoring agent and replaces only the two PNG files in `docs/assets/`.

## License

Project source is available under the [MIT License](LICENSE). Third-party dependencies retain their own licenses.
