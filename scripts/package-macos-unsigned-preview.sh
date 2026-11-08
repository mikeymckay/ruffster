#!/bin/bash
# Package an unsigned, clearly identified development preview. Never changes
# Gatekeeper settings and never installs or starts the monitoring agent.
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Package the Mac preview on macOS." >&2
  exit 1
fi
if [[ "$(uname -m)" != "arm64" ]]; then
  echo "This package is specifically for Apple silicon (arm64)." >&2
  exit 1
fi
if [[ "$#" != 3 ]]; then
  echo "Usage: package-macos-unsigned-preview.sh /absolute/path/to/python /absolute/output/directory source-commit" >&2
  exit 1
fi
PYTHON=$1
OUTPUT=$2
SOURCE_COMMIT=$3
case "$PYTHON:$OUTPUT" in /*:/*) ;; *) echo "Use absolute paths." >&2; exit 1 ;; esac
if [[ ! -x "$PYTHON" ]]; then
  echo "The selected Python executable is unavailable." >&2
  exit 1
fi
if [[ ! "$SOURCE_COMMIT" =~ ^[0-9a-f]{7,40}$ ]]; then
  echo "Pass the source Git commit as a hexadecimal commit ID." >&2
  exit 1
fi

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [[ -n "$(git -C "$ROOT" status --porcelain)" ]]; then
  echo "Package a clean source checkout so the release commit identifies the exact source." >&2
  exit 1
fi
HEAD_COMMIT=$(git -C "$ROOT" rev-parse HEAD)
if [[ "$SOURCE_COMMIT" != "$HEAD_COMMIT" ]]; then
  echo "The source commit must exactly match the checked-out HEAD ($HEAD_COMMIT)." >&2
  exit 1
fi
mkdir -p "$OUTPUT"
DMG="$OUTPUT/Ruffster-unsigned-development-preview-apple-silicon.dmg"
if [[ -e "$DMG" || -e "$OUTPUT/Ruffster Preview.app" ]]; then
  echo "Output already contains a Ruffster preview; choose a new output directory." >&2
  exit 1
fi
WORK=$(mktemp -d "${TMPDIR:-/tmp}/ruffster-dmg.XXXXXXXX")
trap 'rm -rf -- "$WORK"' EXIT HUP INT TERM

"$ROOT/scripts/build-macos-preview.sh" "$PYTHON" "$OUTPUT"
APP="$OUTPUT/Ruffster Preview.app"
DMG_ROOT="$WORK/image"
mkdir -p "$DMG_ROOT"
ditto "$APP" "$DMG_ROOT/Ruffster Preview.app"
ln -s /Applications "$DMG_ROOT/Applications"
cat > "$DMG_ROOT/READ BEFORE OPENING.txt" <<EOF
RUFFSTER — UNSIGNED DEVELOPMENT PREVIEW

This app is not signed or notarized by Apple. It is an experimental preview,
not a supported family installer. Do not use it for ongoing child monitoring.
The app has not had an independent security review. Only use it if you are
comfortable testing early software and have reviewed the source.

Source repository: https://github.com/mikeymckay/ruffster
Source commit: $SOURCE_COMMIT
Build architecture: Apple silicon (arm64)

macOS may block this app because Apple has not verified it. Do not disable
Gatekeeper, remove quarantine, or use a Terminal command to bypass the warning.
If you choose to test it, first read Apple's current instructions and risks:
https://support.apple.com/en-us/102445
Apple's manual “Open Anyway” choice is your decision; stop if the publisher,
source, or downloaded file is unexpected. A checksum helps detect a changed
download; it does not mean Apple or Ruffster has approved the app.

Installing the app does not by itself enable monitoring. Read the project
privacy information and use the visible setup flow together with the computer
user. The preview and its data are experimental.
EOF
hdiutil create -volname "Ruffster unsigned preview" -srcfolder "$DMG_ROOT" -ov -format UDZO "$DMG" >/dev/null
(cd "$OUTPUT" && shasum -a 256 "$(basename "$DMG")" > "$(basename "$DMG").sha256")
echo "Unsigned development preview created: $DMG"
echo "SHA-256: $OUTPUT/$(basename "$DMG").sha256"
echo "Source commit: $SOURCE_COMMIT"
echo "No signing, notarization, quarantine removal, or monitoring installation was performed."
