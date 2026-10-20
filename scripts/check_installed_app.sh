#!/usr/bin/env bash
# Launch the installed Nodecraft.app and check what can be checked without seeing its window:
# the shell starts, the bundled backend answers, the database is at the newest schema,
# and after quitting no Nodecraft process is left behind. Needs the app to be installed.
set -euo pipefail
APP="${1:-/Applications/Nodecraft.app}"
LOG="$HOME/Library/Logs/Nodecraft/backend.log"
DB="$HOME/Library/Application Support/Nodecraft/nodecraft.db"
fail() { echo "FAIL $1"; exit 1; }
pass() { echo "PASS $1"; }

[ -d "$APP" ] || fail "no app at $APP"
codesign --verify --deep "$APP" 2>/dev/null && pass "signature verifies (ad-hoc)" || fail "signature does not verify"
pgrep -f "$APP/Contents/MacOS/nodecraft" >/dev/null && { osascript -e 'quit app "Nodecraft"' || true; sleep 6; }

before=$(wc -l < "$LOG" 2>/dev/null || echo 0)
open "$APP"
for _ in $(seq 1 40); do
  sleep 0.5
  if tail -n +"$((before + 1))" "$LOG" 2>/dev/null | grep -q "GET /api/v1/workflows"; then break; fi
done
tail -n +"$((before + 1))" "$LOG" | grep -q "GET /api/v1/workflows" && pass "the UI loaded and talked to the bundled backend" || fail "no UI request reached the backend"
pgrep -f "$APP/Contents/Resources/runtime/python/bin/python3.12" >/dev/null && pass "bundled Python runtime is running" || fail "no bundled runtime process"

head_rev=$(ls "$(dirname "$0")/../backend/app/storage/migrations/versions" | grep -E '^[0-9]{4}_' | sort | tail -1 | cut -c1-4)
db_rev=$(sqlite3 "$DB" "select version_num from alembic_version" 2>/dev/null || echo none)
[ "$db_rev" = "$head_rev" ] && pass "database is at schema $db_rev" || fail "database at $db_rev, expected $head_rev"

osascript -e 'quit app "Nodecraft"' >/dev/null
sleep 8
left=$( (pgrep -f "Nodecraft.app" || true) | wc -l | tr -d ' ')
[ "$left" = "0" ] && pass "no Nodecraft process left after quitting" || fail "$left Nodecraft processes still running"
echo "installed app check passed"
