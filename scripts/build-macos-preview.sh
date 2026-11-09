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
VERSION=${RUFFSTER_VERSION:-0.1.17}
case "$PYTHON:$OUTPUT" in /*:/*) ;; *) printf '%s\n' 'Use absolute paths.' >&2; exit 1;; esac
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
"$PYTHON" - "$VERSION" <<'PY'
import re, sys
if not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", sys.argv[1]):
    raise SystemExit('Ruffster version must use three numeric components, such as 0.1.17.')
PY
"$PYTHON" -c 'import PyInstaller, nacl, cryptography'
mkdir -p "$OUTPUT"
WORK=$(mktemp -d "${TMPDIR:-/tmp}/family-build.XXXXXXXX")
trap 'rm -rf -- "$WORK"' EXIT HUP INT TERM
APP="$OUTPUT/Ruffster.app"
if [ -e "$APP" ]; then
  printf '%s\n' 'The output app already exists; choose a new output directory.' >&2; exit 1
fi
"$PYTHON" -m PyInstaller --noconfirm --clean --onedir --console --name FamilyActivityCore \
  --paths "$ROOT" --add-data "$ROOT/family_activity/parent_assets:family_activity/parent_assets" \
  --distpath "$WORK/dist" --workpath "$WORK/work" --specpath "$WORK" "$ROOT/scripts/frozen_main.py"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/helpers" "$APP/Contents/Resources/runtime"
cp -R "$WORK/dist/FamilyActivityCore/." "$APP/Contents/Resources/runtime/"
cp "$ROOT/LICENSE" "$APP/Contents/Resources/LICENSE"
ICONSET="$WORK/Ruffster.iconset"
mkdir "$ICONSET"
sips -s format png -z 16 16 "$ROOT/native/macos/ruffster-app-icon.png" --out "$ICONSET/icon_16x16.png" >/dev/null
sips -s format png -z 32 32 "$ROOT/native/macos/ruffster-app-icon.png" --out "$ICONSET/icon_16x16@2x.png" >/dev/null
sips -s format png -z 32 32 "$ROOT/native/macos/ruffster-app-icon.png" --out "$ICONSET/icon_32x32.png" >/dev/null
sips -s format png -z 64 64 "$ROOT/native/macos/ruffster-app-icon.png" --out "$ICONSET/icon_32x32@2x.png" >/dev/null
sips -s format png -z 128 128 "$ROOT/native/macos/ruffster-app-icon.png" --out "$ICONSET/icon_128x128.png" >/dev/null
sips -s format png -z 256 256 "$ROOT/native/macos/ruffster-app-icon.png" --out "$ICONSET/icon_128x128@2x.png" >/dev/null
sips -s format png -z 256 256 "$ROOT/native/macos/ruffster-app-icon.png" --out "$ICONSET/icon_256x256.png" >/dev/null
sips -s format png -z 512 512 "$ROOT/native/macos/ruffster-app-icon.png" --out "$ICONSET/icon_256x256@2x.png" >/dev/null
sips -s format png -z 512 512 "$ROOT/native/macos/ruffster-app-icon.png" --out "$ICONSET/icon_512x512.png" >/dev/null
sips -s format png -z 1024 1024 "$ROOT/native/macos/ruffster-app-icon.png" --out "$ICONSET/icon_512x512@2x.png" >/dev/null
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/Ruffster.icns"
swiftc "$ROOT/native/macos/setup.swift" -o "$APP/Contents/MacOS/FamilyActivitySetup"
swiftc "$ROOT/native/macos/foreground.swift" -o "$APP/Contents/Resources/helpers/foreground"
swiftc "$ROOT/native/macos/status.swift" -o "$APP/Contents/Resources/helpers/status"
"$APP/Contents/Resources/helpers/status" --self-test-state
"$PYTHON" - "$APP/Contents/Info.plist" "$VERSION" <<'PY'
import plistlib, sys
with open(sys.argv[1], 'wb') as file:
    plistlib.dump({'CFBundleName':'Ruffster', 'CFBundleDisplayName':'Ruffster',
                   'CFBundleIdentifier':'org.ruffster.app', 'CFBundleExecutable':'FamilyActivitySetup',
                   'CFBundlePackageType':'APPL', 'CFBundleIconFile':'Ruffster.icns',
                   'CFBundleShortVersionString':sys.argv[2],
                   'CFBundleVersion':sys.argv[2], 'NSHighResolutionCapable':True,
                   'NSLocalNetworkUsageDescription': 'Ruffster uses your local network when you connect a parent computer or send an encrypted report.'}, file)
PY
"$APP/Contents/MacOS/FamilyActivitySetup" --check-bundle
"$APP/Contents/MacOS/FamilyActivitySetup" --self-test-ui \
  "$APP/Contents/Resources/runtime/FamilyActivityCore" "$APP/Contents/Resources/runtime" \
  "$APP/Contents/Resources/helpers/foreground" "$APP/Contents/Resources/helpers/status"
test -s "$APP/Contents/Resources/LICENSE"
"/usr/bin/codesign" --force --deep --sign - "$APP"
"/usr/bin/codesign" --verify --deep --strict --verbose=2 "$APP"
"$APP/Contents/Resources/runtime/FamilyActivityCore" --help >/dev/null
"$PYTHON" "$ROOT/scripts/validate-macos-preview-bundle.py" "$APP"
printf 'Unsigned Ruffster app created: %s\n' "$APP"
