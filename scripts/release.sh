#!/usr/bin/env bash
# Make a distributable Nodecraft.dmg that opens on any Mac without a Gatekeeper warning.
#
# Needs an Apple Developer account (the paid programme). Nothing here can be done without one:
#   APPLE_SIGNING_IDENTITY  "Developer ID Application: Your Name (TEAMID)"   (from your keychain)
#   APPLE_ID                the Apple ID used for notarisation
#   APPLE_TEAM_ID           your 10-character team id
#   APPLE_APP_PASSWORD      an app-specific password (appleid.apple.com > Sign-In and Security)
#
#   scripts/release.sh
#
# Without those variables it stops with the list of what is missing, rather than shipping an app that
# macOS will refuse to open.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/apps/web/src-tauri/target/release/bundle/macos/Nodecraft.app"
OUT="$ROOT/dist"
VERSION="$(grep -m1 '"version"' "$ROOT/apps/web/src-tauri/tauri.conf.json" | sed 's/[^0-9.]//g')"

missing=()
for v in APPLE_SIGNING_IDENTITY APPLE_ID APPLE_TEAM_ID APPLE_APP_PASSWORD; do
  [[ -n "${!v:-}" ]] || missing+=("$v")
done
if ((${#missing[@]})); then
  echo "Cannot make a release build. Set: ${missing[*]}" >&2
  echo "See the comments at the top of this script." >&2
  exit 1
fi

echo "==> build"
"$ROOT/scripts/build_app.sh"

echo "==> sign with the Developer ID (hardened runtime) so it can be notarised"
# Sign every nested binary first (the bundled Python runtime has many), then the app itself.
find "$APP/Contents" -type f \( -perm -u+x -o -name '*.dylib' -o -name '*.so' \) -print0 |
  xargs -0 -n1 codesign --force --options runtime --timestamp --sign "$APPLE_SIGNING_IDENTITY" 2>/dev/null || true
codesign --force --deep --options runtime --timestamp --sign "$APPLE_SIGNING_IDENTITY" "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"

echo "==> disk image"
mkdir -p "$OUT"
DMG="$OUT/Nodecraft-$VERSION.dmg"
rm -f "$DMG"
hdiutil create -volname "Nodecraft" -srcfolder "$APP" -ov -format UDZO "$DMG" >/dev/null
codesign --force --timestamp --sign "$APPLE_SIGNING_IDENTITY" "$DMG"

echo "==> notarise (Apple scans it; usually a few minutes)"
xcrun notarytool submit "$DMG" --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" \
  --password "$APPLE_APP_PASSWORD" --wait
xcrun stapler staple "$DMG"

echo "==> check what a customer's Mac will say"
spctl -a -t open --context context:primary-signature -vv "$DMG"
echo "release ready: $DMG"
