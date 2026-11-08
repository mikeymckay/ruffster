# macOS signing and candidate packaging

`scripts/package-macos-candidate.sh` builds a drag-to-Applications disk image from the current preview sources, signs each Mach-O payload and the app with a Developer ID Application identity, notarizes and staples the app and disk image, and verifies their signatures. The disk image contains `Ruffster Preview.app` and an Applications shortcut. The underlying unsigned preview builder compiles all native helpers and runs `scripts/validate-macos-preview-bundle.py` against the built app, which starts the frozen parent dashboard on loopback with temporary data and checks that unauthenticated API requests are rejected. This smoke check does not install a LaunchAgent or open a native setup window.

This produces a **signed preview candidate**, not a family release. It does not change the setup disclosures or satisfy the open accessibility, usability, privacy, security, and release gates. Keep candidate downloads private to the development team; do not link them from the public site.

## Prerequisites

- Build on a supported Mac with Xcode command-line tools, Python, PyInstaller, and the app's Python dependencies.
- Install a valid **Developer ID Application** signing identity in the build account's keychain. The script refuses missing or non-Developer-ID identities.
- Create a `notarytool` keychain profile using Apple Developer credentials. The profile name is not a password; Apple credentials and API keys stay in Keychain and must not be placed in project files or logs.
- Select a bundle identifier controlled by the distributing developer and a release candidate version.

Apple requires a Developer ID signature, hardened runtime, and a secure timestamp for notarized software. Apple's `notarytool` submits the app and disk image, and `stapler` attaches the resulting tickets. See [Apple's notarization requirements](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution), [custom notarization workflow](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow), and [Developer ID overview](https://developer.apple.com/developer-id/).

## Build a private candidate

After the notary profile and signing identity are installed, set the candidate metadata in the current shell:

```sh
export FAMILY_ACTIVITY_SIGNING_IDENTITY='Developer ID Application: Your Name (TEAMID)'
export FAMILY_ACTIVITY_NOTARY_PROFILE='family-activity-notary'
export FAMILY_ACTIVITY_BUNDLE_ID='org.yourdomain.familyactivity.preview'
export FAMILY_ACTIVITY_VERSION='0.1.0'
```

Then package the app:

```sh
scripts/package-macos-candidate.sh \
  "$(pwd)/.venv/bin/python" \
  "$(pwd)/dist"
```

The output file is a notarized `.dmg` for the architecture of the build Mac. Open it, drag the app into Applications, eject the disk image, then open the copied app. The setup still describes this build as a preview and says it is not ready for family deployment.

## Current validation state

The Mac build machine currently has no valid code-signing identities. The script's signing, notarization, Gatekeeper, first-launch, and signed-package replacement paths therefore remain unvalidated. Only its source checks and missing-identity failure path can be exercised until a Developer ID identity and notary profile are available. A successful notarization is not a substitute for the app's separate family-release gates.

## Restart monitoring after a same-location app replacement

The preview has no automatic updater. After replacing the app in the same location, open it and choose **More options → Restart after app update**. Confirm the restart, then verify the visible menu-bar status returns to on. This restarts only the existing LaunchAgent, preserving its parent connection, collection choices, retention setting, and encrypted report. If the app moved to another location, this action refuses to restart it; remove the agent and set it up again from the new location. The restart path was validated with the real Mac LaunchAgent and synthetic activity, but replacement of a signed, notarized app and rollback to an earlier release remain unverified.

## Exercise install and removal without collecting activity

On a logged-in Mac with the project installed in a Python environment, run:

```sh
python scripts/validate-macos-install-flow.py
```

This creates a temporary home directory, test key, and uniquely named LaunchAgent. The job runs only a shell wrapper that sleeps; it does not invoke the Ruffster collector or its native helpers. The script checks that the real installer registers and starts the job, that launchd restarts it after `SIGKILL`, and that uninstall stops it while retaining its local setup files by default. Temporary files are removed when the script finishes. The native macOS GitHub Actions package job now runs this disposable lifecycle check when CI is triggered. This is lifecycle validation, not a child-activity collection test or a physical sleep/wake test.

## Validate the encrypted agent through the real installer

On a logged-in Mac with the project dependencies installed, run:

```sh
python scripts/validate-macos-agent-runtime.py
```

This compiles the status companion, runs the agent with a synthetic foreground helper, and records encrypted samples without reading the real foreground app or collecting network, DNS, proxy, or browser observations. It suspends the direct test process briefly to check gap recording, then uses the real installer to create a uniquely named temporary LaunchAgent with network collection disabled, kills that agent to verify launchd restart, and uninstalls it while checking that the encrypted report is retained by default. The helper can display a temporary Ruffster menu-bar item in the signed-in Mac session. The test removes its synthetic data and temporary home when cleanup succeeds.

If launchd refuses to boot out the temporary job, the validator preserves the synthetic fixture directory and prints its path. Boot out the `org.familyactivity.validation.<id>` job before deleting that directory. This is developer validation of installer-to-agent wiring, not an interactive setup review, real activity test, physical sleep/wake test, or family release check.
