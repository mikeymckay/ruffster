# Ruffster

**Make computer use easier to talk about.** Ruffster helps parents and children look at everyday computer use together, especially during school hours. It gives families a clearer picture to discuss, keeps monitoring visible, and encrypts reports for the parent. Our golden retriever mascot is here to make those conversations feel a little easier.

<p align="center"><img src="docs/assets/ruffster-mascot.webp" alt="Ruffster golden retriever mascot" width="190"></p>

**Ruffster for Mac 0.1.13 is available for families.** Start on the parent Mac, then set up Marcus's and Annika's Macs together and bring encrypted reports back to the parent dashboard. Setup waits for the first encrypted sample, and if nearby-computer pairing fails it offers a direct retry or connection-file choice with Wi-Fi permission help. Windows setup and packaging pass automated checks, and still need review on a logged-in Windows computer before a Windows download is offered.

[Download Ruffster for Mac 0.1.13 (.dmg)](https://github.com/mikeymckay/ruffster/releases/download/mac-family-0.1.13/Ruffster-Mac-Family-App-Apple-Silicon.dmg) · [Release notes and checksum](https://github.com/mikeymckay/ruffster/releases/tag/mac-family-0.1.13) · [How to get started](https://mikeymckay.github.io/ruffster/install.html)

[Project website](https://mikeymckay.github.io/ruffster/) · [Install guide](https://mikeymckay.github.io/ruffster/install.html) · [Progress page](https://mikeymckay.github.io/ruffster/progress.html) · [FAQ](https://mikeymckay.github.io/ruffster/faq.html) · [Privacy and children's rights](PRIVACY-AND-CHILDREN.md) · [Implementation plan](PLAN.md)

> **Platform priority:** macOS first, then Windows. Linux is a development and test host only; Linux is not a student-facing target in the current scope.

## A look at Ruffster

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

## What Ruffster can show

| Observation | Current behavior | Limit |
| --- | --- | --- |
| Foreground application | Sampled application name | Time between matching samples is only an estimate and may include idle time. |
| Network traffic | Today and past-seven-day sums of recorded byte-counter changes per interface, plus estimated school-hour and Home-, School-, and Other-labeled network breakdowns. macOS also offers an opt-in experimental process-byte summary. | Schedule estimates apportion interface intervals by the chosen hours; router estimates use the last parent-labeled hint. Interfaces may overlap and intervals may be missed. Optional process totals can be assigned to helper services, miss short connections, and do not identify websites. |
| Monitoring coverage | On Mac, the per-user agent starts when the child signs in and macOS relaunches it after an unexpected stop. Sessions, heartbeats, and observable gaps are recorded; the menu-bar and Windows tray companions show starting, recent-sample, and overdue states. The Mac helper exposes explicit screen-reader labels and help. | A gap does not establish whether the cause was sleep, a crash, permissions, removal, or something else. The Windows indicator still needs interactive review on a family computer; the rendered Mac menu item and actual VoiceOver behavior also need review. |
| Network changes | Mac setup records a pseudonymous hint when the default router changes; the experimental Windows preview is wired to do the same. The raw router address is not saved. | Windows PowerShell behavior has not been verified on a Windows computer. A router hint is not proof of location, and router detection can be unavailable. |
| DNS, proxy, and VPN indicators | Reduced true/false/unknown indicators; Windows checks built-in VPN profiles | These indicators are incomplete and cannot confirm filtering works. Third-party VPNs may not be detected. |
| Website names | Optional experimental browser add-on on the child's computer; no add-on is needed on the parent's computer or to use the main app. | It only works in browsers where installed, so the child can turn it off or use another browser. It is not complete website monitoring and is not part of supported setup. It sends domain names only, never private-window domains or full URLs, and has a visible pause control. Missing website details do not tell us why they are missing. |

The school-hours view uses a schedule chosen by the parent; it does not prove that the computer was at school. Home-, School-, and Other-labeled network views use family labels on router hints; they can be wrong or unavailable. The School-labeled network view is separate from the schedule-based school-hours view, and the estimates can overlap.

## Privacy and encryption

Ruffster encrypts each activity report for the parent. The parent keeps the private key and a six-digit PIN; the child's computer can send a report but cannot open it. Save the encrypted recovery copy so you can restore parent access on another computer. No cloud account is required.

To connect computers, the sending computer shows two digits and the receiving computer enters them. This helps the devices find each other on the same Wi-Fi; the report itself stays encrypted. Some Wi-Fi networks keep devices separate. If that happens, save an encrypted report file on the child's computer and open it in the parent's dashboard. The dashboard can keep reports from several computers separate and lets the parent name each one.

The parent's key is kept on the parent's computer. The child computer stores encrypted report content, along with basic file details such as record count and timestamps. As with any app on a computer, the signed-in user or administrator can manage software on that computer. Keep the parent key backup and PIN together somewhere you can find them; they let you restore reports on a new parent computer. Older recovery copies still use their original passphrase.

The monitoring agent now refuses to start without the parent's public key and writes activity only as encrypted records. Earlier prototype databases and low-level test utilities may contain plaintext; they are not automatically migrated or erased. The dashboard can still open an older local plaintext database, so check existing files before sharing or retaining them. For a supported old prototype schema, the developer CLI can create an encrypted copy while leaving the source untouched:

```sh
python -m family_activity encrypt-legacy \
  --source /path/to/old-activity.sqlite3 \
  --public-key /path/to/ruffster-public.key \
  --output /path/to/activity-encrypted.sqlite3 \
  --retention-days 30
```

The command applies retention to original event times and omits expired rows. Verify the encrypted copy before deciding what to do with the old source file. Encrypted collection and parent setup continue to improve with family use.

See [ENCRYPTION.md](ENCRYPTION.md) for the threat model and known limitations, and [AGENTS.md](AGENTS.md) for development rules.

The engineering requirements and open European privacy and children's-rights questions are recorded in [PRIVACY-AND-CHILDREN.md](PRIVACY-AND-CHILDREN.md). This is not a legal compliance determination; review by qualified counsel is needed before broader distribution.

## Delivery priorities

1. **Make macOS dependable first.** Validate setup and removal, visible status, sleep/wake, permissions, user changes, restart recovery, encrypted reports, and key recovery on real Macs. Keep the unsigned download easy to identify and include its source, checksum, and a short note about Apple's first-open prompt. Revisit signing and notarization as the project grows.
2. **Bring the family flow to Windows.** Test installation, startup and recovery, visible tray status, network and app observations, encrypted report handoff, parent dashboard, updates, and removal on real Windows computers.
3. **Make the public project experience excellent.** Keep this README useful to a parent arriving for the first time and to a contributor; publish a polished GitHub Pages home page, family installation guide, progress page, and plain-language FAQ. Include current synthetic screenshots, clear readiness status, accessible responsive layouts, and clearly explain that the Mac app is an unsigned GitHub release.
4. **Validate with families and reviewers.** Observe nontechnical parents and children using the whole flow; complete accessibility, security, privacy, and European children's rights reviews.

Linux remains a low-priority development and test host. It is not a student-facing platform target. The task list and release gates are in [PLAN.md](PLAN.md); the Pages design and launch checklist is in [GITHUB-PAGES.md](GITHUB-PAGES.md).

See the full [implementation plan](PLAN.md). Website source is in [`docs/`](docs/), and [GITHUB-PAGES.md](GITHUB-PAGES.md) explains the intended deployment.

## Developer quick start

Use Python 3.10 or newer. Linux is useful for running the shared tests, but test success on Linux is not evidence that macOS or Windows behavior works.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python scripts/run-tests.py
node --check family_activity/parent_assets/app.js
```

For local UI development, start the experimental parent app:

```sh
.venv/bin/python -m family_activity parent
```

It binds to loopback. The default CLI database and dashboard are developer tools, not a family installation path. Do not expose them to a network.

GitHub Actions runs the test suite on Linux, macOS, and Windows and checks both native packages. A `mac-family-*` release tag runs the Mac suite and publishes the unsigned Apple-silicon family app with its source commit and SHA-256 checksum. The repository is at [github.com/mikeymckay/ruffster](https://github.com/mikeymckay/ruffster); the family-friendly [Ruffster website and install guide](https://mikeymckay.github.io/ruffster/) are live.

The test runner prints each test and emits Python stack traces every five minutes if a job stalls; CI also places those traces in the job summary and stops a test job after 20 minutes.

### Build experimental previews

**macOS (Apple silicon):** build on a Mac with the project dependencies and PyInstaller installed. The local builder makes an unsigned app bundle. The tagged GitHub workflow packages the app in a drag-to-Applications disk image and publishes it with its source commit and SHA-256 checksum. Since the app is not signed by Apple, macOS asks you to confirm before opening it; follow [Apple's current instructions](https://support.apple.com/en-us/102445) and keep the built-in protection on. See [MACOS-DISTRIBUTION.md](MACOS-DISTRIBUTION.md).

```sh
.venv/bin/python -m pip install -e ".[build]"
./scripts/build-macos-preview.sh "$(pwd)/.venv/bin/python" "$(pwd)/dist/family-activity-preview"
```

**Windows x64:** build on Windows with Python and the .NET 10 LTS SDK. It produces a single-download per-user installer embedded with the app bundle, plus a ZIP with a start guide. The installer copies files before opening the family confirmation flow; it does not enable monitoring by itself. GitHub Actions is configured to run the Windows tests and package checks. The setup and monitoring flow still need an interactive review on a family's Windows computer.

```powershell
python -m pip install -e ".[build]"
.\scripts\build-windows-preview.ps1 -OutputDirectory .\dist\FamilyActivityPreview
```

Read [WINDOWS.md](WINDOWS.md) before working on the Windows preview. A Linux cross-compile checks the C# source only; it cannot validate Windows installation or runtime behavior.

## Project website

The static website source in `docs/` contains the home page, getting-started guide, progress page, FAQ, and screenshots. It has no external runtime dependencies and publishes from the repository's `/docs` folder with GitHub Pages. See [GITHUB-PAGES.md](GITHUB-PAGES.md). Clearly distinguish any unsigned preview from a supported family release.

Refresh the synthetic parent setup and report screenshots with `.venv/bin/python scripts/capture-parent-demo-screenshots.py` (Chrome or Chromium required). The first-run image has no parent key; the report image uses a temporary key and fictional activity records. The tool starts no monitoring agent and replaces only the two PNG files in `docs/assets/`.

## License

Project source is available under the [MIT License](LICENSE). Third-party dependencies retain their own licenses.
