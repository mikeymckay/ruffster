#!/bin/sh
# Build a local, unsigned preview bundle. This script never installs the agent.
set -eu
if [ "$(uname -s)" != "Darwin" ]; then
  printf '%s\n' 'Build this preview on macOS.' >&2; exit 1
fi
if [ "$#" -ne 2 ]; then
  printf '%s\n' 'Usage: build-macos-preview.sh /absolute/path/to/python /absolute/output/directory' >&2; exit 1
fi
PYTHON=$1
OUTPUT=$2
case "$PYTHON:$OUTPUT" in /*:/*) ;; *) printf '%s\n' 'Use absolute paths.' >&2; exit 1;; esac
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
"$PYTHON" -c 'import PyInstaller, nacl, cryptography'
mkdir -p "$OUTPUT"
WORK=$(mktemp -d "${TMPDIR:-/tmp}/family-build.XXXXXXXX")
trap 'rm -rf -- "$WORK"' EXIT HUP INT TERM
APP="$OUTPUT/Family Activity Preview.app"
if [ -e "$APP" ]; then
  printf '%s\n' 'The output app already exists; choose a new output directory.' >&2; exit 1
fi
"$PYTHON" -m PyInstaller --noconfirm --clean --onedir --console --name FamilyActivityCore \
  --paths "$ROOT" --add-data "$ROOT/family_activity/parent_assets:family_activity/parent_assets" \
  --distpath "$WORK/dist" --workpath "$WORK/work" --specpath "$WORK" "$ROOT/scripts/frozen_main.py"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/helpers" "$APP/Contents/Resources/runtime"
cp -R "$WORK/dist/FamilyActivityCore/." "$APP/Contents/Resources/runtime/"
cp "$ROOT/LICENSE" "$APP/Contents/Resources/LICENSE"
swiftc "$ROOT/native/macos/setup.swift" -o "$APP/Contents/MacOS/FamilyActivitySetup"
swiftc "$ROOT/native/macos/foreground.swift" -o "$APP/Contents/Resources/helpers/foreground"
swiftc "$ROOT/native/macos/status.swift" -o "$APP/Contents/Resources/helpers/status"
"$APP/Contents/Resources/helpers/status" --self-test-state
"$PYTHON" - "$APP/Contents/Info.plist" <<'PY'
import plistlib, sys
with open(sys.argv[1], 'wb') as file:
    plistlib.dump({'CFBundleName':'Family Activity Preview', 'CFBundleDisplayName':'Family Activity Preview',
                   'CFBundleIdentifier':'org.familyactivity.preview', 'CFBundleExecutable':'FamilyActivitySetup',
                   'CFBundlePackageType':'APPL', 'CFBundleShortVersionString':'0.1.0',
                   'CFBundleVersion':'1', 'NSHighResolutionCapable':True,
                   'NSLocalNetworkUsageDescription': 'Family Activity uses your local network when you connect a parent computer or send an encrypted report.'}, file)
PY
"$APP/Contents/MacOS/FamilyActivitySetup" --check-bundle
"$APP/Contents/MacOS/FamilyActivitySetup" --self-test-ui \
  "$APP/Contents/Resources/runtime/FamilyActivityCore" "$APP/Contents/Resources/runtime" \
  "$APP/Contents/Resources/helpers/foreground" "$APP/Contents/Resources/helpers/status"
test -s "$APP/Contents/Resources/LICENSE"
"$APP/Contents/Resources/runtime/FamilyActivityCore" --help >/dev/null
"$PYTHON" "$ROOT/scripts/validate-macos-preview-bundle.py" "$APP"
printf 'Unsigned local preview created: %s\n' "$APP"
