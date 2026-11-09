# Mac app distribution

Ruffster currently ships as an unsigned Apple-silicon Mac family app. GitHub Actions builds it from the tagged source, checks the Mac test suite and packaged dashboard, and publishes a drag-to-Applications disk image with its source commit and checksum. The app appears as **Ruffster** in Applications and includes the golden retriever icon.

## Opening Ruffster on Mac

Because this project does not yet have an Apple Developer ID, macOS asks you to confirm the first time Ruffster opens. Follow [Apple's current steps for an app from an identified developer](https://support.apple.com/en-us/102445) for Ruffster; keep your Mac's built-in security settings as they are. The release notes include the source commit and checksum so families can see which build they downloaded. A checksum checks that the file arrived unchanged; it is not a publisher signature.

## How the family app is published

The release workflow runs on the standard `macos-latest` Apple-silicon GitHub Actions runner when a `mac-preview-*` tag is pushed. It runs the Mac test suite, builds and smoke-checks the app, makes a drag-to-Applications disk image, and publishes a GitHub **prerelease** with:

- a note inside the disk image that explains the unsigned first-open step and invites families to review setup together;
- the exact source commit in the release workflow and inside the disk image;
- a SHA-256 checksum sidecar (integrity check only, not a digital signature);
- release notes linking Apple's current Gatekeeper guidance.

The workflow needs no signing secret. To publish a family app prerelease, review the changes, run the Mac workflow, then tag the reviewed commit with a version such as `mac-preview-0.1.6` and push that tag. The prerelease label keeps the app's current status clear while families begin using it.

For a local package on the real Mac, install build dependencies, then run:

```sh
scripts/package-macos-unsigned-preview.sh \
  "$(pwd)/.venv/bin/python" \
  "$(pwd)/dist/ruffster-unsigned-preview" \
  "$(git rev-parse HEAD)"
```

This creates a `.dmg` and adjacent `.sha256` file. It never installs the monitoring agent. Follow [Apple's current first-open instructions](https://support.apple.com/en-us/102445); the package does not change your Mac's built-in security settings.

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

The output file is a notarized `.dmg` for the architecture of the build Mac. Open it, drag the app into Applications, eject the disk image, then open the copied app. The setup introduces the app, explains what it records, and offers separate actions to open the parent dashboard or set up this Mac for a child.

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
