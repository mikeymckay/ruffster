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
DMG="$OUTPUT/Ruffster-Mac-Family-Preview-Apple-Silicon.dmg"
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
RUFFSTER FOR MAC — FAMILY DEVELOPMENT PREVIEW

Ruffster helps parents and children understand computer use together,
including school-day patterns. This build has visible monitoring, encrypted
activity reports, and a local parent dashboard. Set it up together and keep
the menu-bar status visible.

Source repository: https://github.com/mikeymckay/ruffster
Source commit: $SOURCE_COMMIT
Build architecture: Apple silicon (arm64)

This app is not signed or notarized by Apple, so macOS asks you to confirm
before opening it. Open it only if you downloaded it from the Ruffster release
page. Follow Apple's first-open steps here:
https://support.apple.com/en-us/102445
Keep macOS security settings as they are. The checksum alongside the download
checks that the file arrived unchanged.

The setup explains what Ruffster records before monitoring begins. Read it
together and choose the options that fit your family.
EOF
hdiutil create -volname "Ruffster unsigned preview" -srcfolder "$DMG_ROOT" -ov -format UDZO "$DMG" >/dev/null
(cd "$OUTPUT" && shasum -a 256 "$(basename "$DMG")" > "$(basename "$DMG").sha256")
echo "Ruffster Mac family development preview created: $DMG"
echo "SHA-256: $OUTPUT/$(basename "$DMG").sha256"
echo "Source commit: $SOURCE_COMMIT"
echo "No signing, notarization, quarantine removal, or monitoring installation was performed."
