# Ruffster for Mac: install and release

Ruffster is distributed as an unsigned Apple-silicon Mac app. Families can install it without an Apple Developer account. GitHub Actions builds the app from a reviewed source commit, checks its bundled files, and publishes a drag-to-Applications disk image with the source commit and SHA-256 checksum.

## Install Ruffster

1. Download the current Mac disk image from the [Ruffster releases](https://github.com/mikeymckay/ruffster/releases).
2. Open the `.dmg` and drag **Ruffster** to **Applications**.
3. Open Ruffster. If macOS says it cannot verify the developer, choose **Done**, then go to **System Settings → Privacy & Security → Open Anyway** for Ruffster. Open it again and choose **Open**. This approves Ruffster only and leaves the Mac's general app protections on. Follow [Apple's current instructions](https://support.apple.com/en-us/102445). If macOS says the app will damage the computer, don't open it; contact the project.
4. Open Ruffster while signed in to the account that should use it. On the parent's Mac, choose **Open parent dashboard**. On a child's Mac, sign in to the child's account and choose **Set up this Mac together…**. The app may stay in the shared Applications folder; background monitoring and its local report are set up only for the signed-in account.

macOS asks for a first-open confirmation because Ruffster is not signed with an Apple Developer ID. The app bundle has an ad-hoc signature so macOS can check that its files are intact; that is not an Apple publisher signature. The release page provides the source commit and a SHA-256 checksum to check that the download arrived unchanged. Neither one identifies the publisher. Keep macOS protections enabled and review the source and release before installing.

## Publish a Mac family release

The `Publish Mac family app` workflow runs on GitHub's Apple-silicon macOS runner when a `mac-family-*` tag is pushed. It runs the test suite, builds and smoke-checks the app, validates its bundle seal, and publishes a `.dmg` with the exact source commit and checksum. It needs no Apple signing credentials or secrets. Review the commit and successful workflow first; then create and push a version tag such as `mac-family-0.1.21`.

Older `mac-preview-*` tags remain prereleases. New family downloads should use `mac-family-*` releases.

To create the same unsigned package locally on an Apple-silicon Mac with the project's build dependencies installed:

```sh
scripts/package-macos-unsigned-preview.sh \
  "$(pwd)/.venv/bin/python" \
  "$(pwd)/dist/ruffster-unsigned-preview" \
  "$(git rev-parse HEAD)"
```

This writes a `.dmg` and adjacent `.sha256` file. It packages the app only; it does not install or start monitoring.

## Validate startup and updates

On a logged-in Mac, run the disposable launchd lifecycle check:

```sh
.venv/bin/python scripts/validate-macos-install-flow.py
```

It installs a uniquely named temporary LaunchAgent that runs only a sleeping shell script, checks launchd restart after termination, and removes the job. It does not collect activity. GitHub's native Mac package job runs this check.

To test the encrypted agent and visible menu-bar companion with fictional activity, use a logged-in Mac session:

```sh
.venv/bin/python scripts/validate-macos-agent-runtime.py
```

This uses a synthetic foreground helper with network collection disabled, briefly suspends a test process to check gap recording, then checks launchd restart and removal. It does not inspect real foreground apps or collect network, DNS, proxy, or browser observations. It may display a temporary Ruffster status item. The check is developer validation, not a family setup or sleep/wake review. If cleanup cannot remove a test LaunchAgent, the validator preserves the synthetic fixture directory and prints its path; remove that named job before deleting the directory.

Ruffster does not yet update itself. After replacing the app in the same location, open it and choose **More options → Restart after app update**; confirm that the menu-bar status returns to on. If you moved Ruffster, remove its existing setup and set it up again from the new location. The restart has been checked with synthetic activity; family upgrade and rollback still need hands-on review.

## Future signing

The current release path intentionally works without an Apple Developer ID. If the project later obtains one, signing and notarization can be evaluated as an additional convenience for families. That can remove the manual first-open approval, but it is not needed to build or publish the current unsigned release and does not replace the family's choice to review Ruffster and its collection settings.
