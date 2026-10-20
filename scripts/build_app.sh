#!/usr/bin/env bash
# Build Nodecraft.app end to end: runtime -> frontend + shell -> ad-hoc signature -> smoke test.
#   scripts/build_app.sh            build only
#   scripts/build_app.sh --install  also copy to /Applications (replaces an older copy)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="/opt/homebrew/opt/rustup/bin:$HOME/.cargo/bin:$PATH"
APP="$ROOT/apps/web/src-tauri/target/release/bundle/macos/Nodecraft.app"

echo "==> bundled Python runtime"
python3 "$ROOT/scripts/build_runtime.py"

echo "==> frontend + desktop shell"
(cd "$ROOT/apps/web" && pnpm install --frozen-lockfile >/dev/null && pnpm tauri build --bundles app)

echo "==> ad-hoc signing (no Developer ID needed to run on this Mac)"
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

echo "==> smoke test of the runtime inside the app"
python3 "$ROOT/scripts/smoke_runtime.py" "$APP/Contents/Resources/runtime"

echo "built: $APP ($(du -sh "$APP" | cut -f1))"

if [[ "${1:-}" == "--install" ]]; then
  osascript -e 'tell application "Nodecraft" to quit' >/dev/null 2>&1 || true
  sleep 2
  rm -rf /Applications/Nodecraft.app
  cp -R "$APP" /Applications/Nodecraft.app
  codesign --verify --deep --strict /Applications/Nodecraft.app
  echo "installed: /Applications/Nodecraft.app"
fi
