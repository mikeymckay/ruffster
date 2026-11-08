#!/bin/bash
# Create a signed and notarized drag-to-Applications candidate. This does not
# change the product's preview readiness or make it eligible for family release.
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Build and notarize the Mac candidate on macOS." >&2
  exit 1
fi
if [[ "$#" != 2 ]]; then
  echo "Usage: package-macos-candidate.sh /absolute/path/to/python /absolute/output/directory" >&2
  exit 1
fi

PYTHON=$1
OUTPUT=$2
case "$PYTHON:$OUTPUT" in /*:/*) ;; *) echo "Use absolute paths." >&2; exit 1 ;; esac
if [[ ! -x "$PYTHON" ]]; then
  echo "The selected Python executable is unavailable." >&2
  exit 1
fi

IDENTITY=${FAMILY_ACTIVITY_SIGNING_IDENTITY:-}
NOTARY_PROFILE=${FAMILY_ACTIVITY_NOTARY_PROFILE:-}
BUNDLE_ID=${FAMILY_ACTIVITY_BUNDLE_ID:-}
VERSION=${FAMILY_ACTIVITY_VERSION:-}
for setting in IDENTITY NOTARY_PROFILE BUNDLE_ID VERSION; do
  if [[ -z "${!setting}" ]]; then
    echo "Set FAMILY_ACTIVITY_SIGNING_IDENTITY, FAMILY_ACTIVITY_NOTARY_PROFILE, FAMILY_ACTIVITY_BUNDLE_ID, and FAMILY_ACTIVITY_VERSION before packaging." >&2
    exit 1
  fi
done
if [[ ! "$IDENTITY" =~ ^Developer\ ID\ Application: ]]; then
  echo "FAMILY_ACTIVITY_SIGNING_IDENTITY must name a Developer ID Application identity." >&2
  exit 1
fi
if [[ ! "$BUNDLE_ID" =~ ^[a-z0-9][a-z0-9-]*(\.[a-z0-9][a-z0-9-]*)+$ ]]; then
  echo "FAMILY_ACTIVITY_BUNDLE_ID must be a reverse-DNS bundle identifier." >&2
  exit 1
fi
if [[ ! "$VERSION" =~ ^[0-9]+(\.[0-9]+){1,2}$ ]]; then
  echo "FAMILY_ACTIVITY_VERSION must contain two or three numeric version components." >&2
  exit 1
fi

if ! /usr/bin/security find-identity -v -p codesigning | /usr/bin/grep -F "$IDENTITY" | /usr/bin/grep -Fq 'Developer ID Application:'; then
  echo "The selected Developer ID Application identity is not available in this Mac's keychain." >&2
  exit 1
fi

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
mkdir -p "$OUTPUT"
ARCH=$(uname -m)
DMG="$OUTPUT/Ruffster Preview-${VERSION}-macOS-${ARCH}.dmg"
if [[ -e "$DMG" ]]; then
  echo "The candidate already exists; choose a new output directory or remove it explicitly." >&2
  exit 1
fi
WORK=$(mktemp -d "${TMPDIR:-/tmp}/family-candidate.XXXXXXXX")
SUCCESS=0
cleanup() {
  rm -rf -- "$WORK"
  if [[ "$SUCCESS" != "1" ]]; then rm -f -- "$DMG"; fi
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

"$ROOT/scripts/build-macos-preview.sh" "$PYTHON" "$WORK/unsigned"
APP="$WORK/unsigned/Ruffster Preview.app"
"$PYTHON" - "$APP/Contents/Info.plist" "$BUNDLE_ID" "$VERSION" <<'PY'
import plistlib
import sys

path, bundle_id, version = sys.argv[1:]
with open(path, 'rb') as stream:
    info = plistlib.load(stream)
info.update({
    'CFBundleIdentifier': bundle_id,
    'CFBundleName': 'Ruffster Preview',
    'CFBundleDisplayName': 'Ruffster Preview',
    'CFBundleShortVersionString': version,
    'CFBundleVersion': version,
})
with open(path, 'wb') as stream:
    plistlib.dump(info, stream)
PY

# Sign every Mach-O payload before signing the enclosing app bundle.
while IFS= read -r -d '' payload; do
  if /usr/bin/file -b "$payload" | /usr/bin/grep -q 'Mach-O'; then
    /usr/bin/codesign --force --options runtime --timestamp --sign "$IDENTITY" "$payload"
  fi
done < <(/usr/bin/find "$APP" -type f -print0)
/usr/bin/codesign --force --options runtime --timestamp --sign "$IDENTITY" "$APP"
/usr/bin/codesign --verify --deep --strict --verbose=2 "$APP"

# Notarize and staple the app before placing it in a disk image.
APP_ZIP="$WORK/Ruffster Preview-${VERSION}.zip"
/usr/bin/ditto -c -k --sequesterRsrc --keepParent "$APP" "$APP_ZIP"
xcrun notarytool submit "$APP_ZIP" --keychain-profile "$NOTARY_PROFILE" --wait --output-format json > "$WORK/app-notary.json"
APP_STATUS=$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("status", ""))' "$WORK/app-notary.json")
if [[ "$APP_STATUS" != "Accepted" ]]; then
  echo "The app was not accepted for notarization. Notary result:" >&2
  cat "$WORK/app-notary.json" >&2
  exit 1
fi
xcrun stapler staple "$APP"
xcrun stapler validate "$APP"

# The disk image opens with the app and a standard Applications shortcut.
DMG_ROOT="$WORK/dmg-root"
mkdir -p "$DMG_ROOT"
ditto "$APP" "$DMG_ROOT/Ruffster Preview.app"
ln -s /Applications "$DMG_ROOT/Applications"
hdiutil create -volname "Ruffster Preview" -srcfolder "$DMG_ROOT" -ov -format UDZO "$DMG"
/usr/bin/codesign --force --timestamp --sign "$IDENTITY" "$DMG"
xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait --output-format json > "$WORK/dmg-notary.json"
DMG_STATUS=$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("status", ""))' "$WORK/dmg-notary.json")
if [[ "$DMG_STATUS" != "Accepted" ]]; then
  echo "The disk image was not accepted for notarization. Notary result:" >&2
  cat "$WORK/dmg-notary.json" >&2
  exit 1
fi
xcrun stapler staple "$DMG"
xcrun stapler validate "$DMG"
/usr/bin/codesign --verify --deep --strict --verbose=2 "$APP"
SUCCESS=1
echo "Signed and notarized preview candidate created: $DMG"
echo "This candidate remains a preview and is not approved for family deployment."
