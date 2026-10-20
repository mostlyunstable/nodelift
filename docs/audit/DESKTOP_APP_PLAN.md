# Desktop app plan (macOS first)

Audit date 2026-10-18. Goal: a Nodecraft.app in `/Applications`, launched from Spotlight/Dock, no Terminal, no manual
localhost, data that survives upgrades. Wrapping the current web UI does **not** by itself solve backend lifecycle,
Python distribution, auth or storage — those are the real work.

## 1. Facts about this machine and codebase (measured)

| Fact                                                                                                                                              | Consequence                                                                                                                        |
| ------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| macOS 26.5, arm64, 869 GB free                                                                                                                    | Target Apple Silicon first; Intel/universal later                                                                                  |
| Node 26, pnpm 12, uv 0.13 present                                                                                                                 | Frontend and Python tooling ready                                                                                                  |
| **No Rust** (`cargo`/`rustc` missing), only Command Line Tools (no full Xcode)                                                                    | Tauri needs `rustup` (~1.5 GB, 10–15 min); CLT is enough for macOS bundles                                                         |
| **0 code-signing identities**                                                                                                                     | No Developer ID yet. A locally built, ad-hoc-signed app runs on this Mac; sharing it needs right-click→Open until signed/notarized |
| Frontend production build works: `index-*.js` 432 kB (136 kB gzip), CSS 20 kB                                                                     | Small; Monaco is **not** in it                                                                                                     |
| Monaco loads from `cdn.jsdelivr.net/npm/monaco-editor@0.55.1` (string found in the bundle)                                                        | Breaks offline and under a strict CSP; must be bundled                                                                             |
| Backend assumes a source checkout: worker = `sys.executable -I worker_entry.py`, Alembic via `BACKEND_DIR`, `reload=True`, data in `~/.nodecraft` | Needs refactoring before any packaging (ARCH-3)                                                                                    |
| Worker uses `resource` (POSIX)                                                                                                                    | Windows needs Job Objects; Linux/macOS fine                                                                                        |

## 2. Options

|                         | Tauri 2                                                                    | Electron                                | Other (native Swift shell, pywebview) |
| ----------------------- | -------------------------------------------------------------------------- | --------------------------------------- | ------------------------------------- |
| Shell size              | ~10–20 MB (estimate)                                                       | ~110–150 MB (estimate)                  | small / small                         |
| Webview                 | System WKWebView on macOS                                                  | Bundled Chromium (identical everywhere) | WKWebView                             |
| Lifecycle glue language | Rust (≈150–250 lines: spawn, readiness, shutdown, single-instance)         | TypeScript (same language as the app)   | Swift / Python                        |
| Sidecar support         | First-class (`externalBin`, `resources`), shell plugin                     | Plain `child_process`                   | manual                                |
| Updater                 | `tauri-plugin-updater` (own minisign keys, static JSON on GitHub Releases) | `electron-updater` (mature)             | none                                  |
| Risk for this repo      | New toolchain; WKWebView differences                                       | Heavy download; more memory             | Weak ecosystem / tooling              |
| Windows/Linux later     | Yes (WebView2 / WebKitGTK)                                                 | Yes, most uniform                       | Mostly no                             |

Evidence on webview compatibility: the whole UI (React Flow, Monaco, EventSource/SSE, fetch) worked in the in-app
browser I used for every verification in this audit; the process list showed WebKit WebContent processes, so it was
very likely WKWebView-class. That is indicative, not proof — the spike must confirm in a real Tauri window.

**Recommendation: Tauri 2 + bundled Python runtime sidecar, gated by a 1–2 day spike. Fall back to Electron if the
spike shows WKWebView problems (Monaco workers, EventSource behaviour, CSP) or Rust friction.** Reasoning: the app has
no Node-side code to reuse, the shell's only jobs are process lifecycle and windowing, a small shell costs less to ship
and update, and the Python sidecar problem is identical in both frameworks. Do not rewrite the frontend either way.

## 3. Recommended architecture

```
Nodecraft.app
├─ Contents/MacOS/nodecraft            Tauri shell (Rust): window, menu, lifecycle, updater
├─ Contents/Resources/
│   ├─ web/                            built frontend (Vite dist, Monaco bundled)
│   └─ runtime/
│       ├─ python/                     python-build-standalone 3.12 (full stdlib)
│       ├─ site-packages/              backend deps + `app/` package, pre-installed at build time
│       └─ bin/nodecraft-backend       tiny launcher: exec python -m app.desktop_main
└─ user data (outside the bundle)
    ~/Library/Application Support/Nodecraft/{nodecraft.db, backups/, settings.json}
    ~/Library/Logs/Nodecraft/{backend.log, shell.log}
```

Why a bundled **runtime** instead of a PyInstaller exe: user code must be able to `import csv, datetime, statistics,
sqlite3 …` (the whole stdlib) and, later, installed packages. A frozen exe contains only what the backend imported,
so user code would fail on ordinary imports and workers would need a self-reexec hack. The runtime also keeps
`python -I worker_entry.py` working unchanged and enables per-workflow dependencies later. Cost: every Mach-O in the
runtime must be signed (below) and the bundle is larger. Size is an estimate (~150–200 MB); the spike must measure it.

### Process lifecycle

1. Shell starts → single-instance lock (second launch focuses the window).
2. Shell picks a free loopback port (bind `127.0.0.1:0`, release) and generates a 256-bit random token.
3. Shell spawns `nodecraft-backend` in its own process group with env: port, token, data dir, log dir.
4. **Readiness:** shell polls `GET /api/v1/health` (token) every 100 ms, 20 s budget. Splash screen shows progress.
5. Frontend receives `{baseUrl, token}` via a Tauri command (never from a URL or localStorage) and uses it for all
   requests. SSE moves from `EventSource` to fetch-streaming (headers allowed) or a short-lived stream token.
6. **Failure:** if the backend exits or readiness times out, show an error page: reason, last 200 log lines,
   _Open logs folder_, _Copy diagnostics_, _Retry_. Never an endless spinner.
7. **Shutdown:** on quit the shell calls `POST /api/v1/system/shutdown`, waits 5 s, then SIGTERM the group, then
   SIGKILL at 8 s. The backend cancels live runs and marks them failed (already implemented for restarts); workers
   self-exit if the backend dies (already implemented and tested).
8. **Crash recovery:** the shell restarts the backend up to 3 times with backoff; the frontend's SSE reconnect and
   status watchdog (already verified when the API was killed mid-run) recover the view; interrupted runs show as
   failed and can be resumed.

### Security of the loopback service

Token required on every route; `Host` allowlist; `Origin` allowlist (`tauri://localhost`); no CORS wildcard; bind
`127.0.0.1` only (already enforced). Fixes SEC-1; it is a hard prerequisite, not polish.

### Data, migration, backup

- New location `~/Library/Application Support/Nodecraft/`. On first launch, if `~/.nodecraft/nodecraft.db` exists and
  the new DB doesn't, **copy** (never move) it using the SQLite backup API, verify with `PRAGMA integrity_check`,
  keep the original untouched. Today `~/.nodecraft` holds an empty database (0 workflows, 0 runs, measured), so
  migration risk is low now and grows with every user — do this early.
- Before applying any Alembic migration, copy the DB to `backups/nodecraft-<schema>-<timestamp>.db`; keep the last 5. If a migration fails, restore the copy and show a clear error.
- Settings in `settings.json` (or a settings table); autosave drafts in the DB.
- _Export all data_ (zip of DB + workflows as JSON) in the app menu.

### Logging and diagnostics

Rotating `backend.log` (structured, no request bodies, no secrets) and `shell.log`; a Diagnostics dialog showing app
version, schema version, data/log paths, backend port (not token), health, last errors, with _Copy_ and
_Reveal in Finder_. Today there are no log files at all (uvicorn writes to stdout only).

### Dev vs production

- Dev: `pnpm tauri dev` → Vite dev server + backend launched from the repo with `uv run` (no reload, token disabled
  only with an explicit `NODECRAFT_DEV=1`).
- Prod: bundled `web/` + bundled runtime. A single `make desktop` builds both and runs the smoke test below.

### Signing, notarization, distribution

- Ad-hoc signing is enough for a local build on this Mac.
- To distribute: Apple Developer Program membership (paid) → Developer ID Application certificate → sign **every**
  Mach-O in the bundle (python, `.so`, `.dylib`) with the hardened runtime and the needed entitlements
  (`com.apple.security.cs.allow-unsigned-executable-memory` is typically needed for CPython/ctypes — verify in the
  spike), then notarize with `notarytool` and staple. Plan a day for the first signing pass.
- DMG via the Tauri bundler; GitHub Releases as the host.

### Updates

`tauri-plugin-updater` with a minisign key pair and a `latest.json` on GitHub Releases. The updater replaces the app,
not user data; the backup-before-migrate step protects the database across upgrades. Show the version in
_About_ and in diagnostics. Do this after notarization works; unsigned auto-update is a poor experience.

### Performance targets (to be measured, not promised)

Cold start to interactive window < 3 s on this Mac; warm start < 1.5 s; idle memory < 400 MB including the backend;
installer < 250 MB. The spike records the actual numbers.

### Windows / Linux later

Frontend and shell port as is. Backend work: POSIX `resource` limits → Windows Job Objects; `start_new_session`/
`killpg` → process trees on Windows; python-build-standalone exists for both; data dirs via platform paths. Do not
start until the macOS app is stable.

## 4. Incremental plan (nothing destructive; web version keeps working throughout)

| Step | Work                                                                                                                                                                                                                | Effort | Acceptance                                                                                                                                         |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| D0   | **Spike**: install Rust; Tauri window loading the existing built UI; spawn the dev backend with a random port and token; confirm Monaco (bundled), SSE, React Flow in WKWebView; measure start time and bundle size | M      | A window shows the app, runs a workflow, streams events; written go/no-go with numbers                                                             |
| D1   | Backend refactor: runtime config object (data dir, port, token, python/worker command), `importlib.resources` for migrations, reload off by default, `/system/shutdown`, token + Host/Origin middleware             | M      | All tests pass; unauthenticated/foreign-Host requests rejected; `python -m app.desktop_main` runs from an arbitrary directory                      |
| D2   | Bundle Monaco locally; configurable API base URL + token in the frontend; SSE over fetch                                                                                                                            | M      | App works with networking disabled; no request goes to jsDelivr                                                                                    |
| D3   | Runtime build script: python-build-standalone + `pip install` backend into `site-packages`; smoke test that a worker can `import csv, sqlite3, datetime`                                                            | M      | Fresh machine-like run (empty `PATH`) executes a workflow                                                                                          |
| D4   | Tauri shell lifecycle: free port, token, readiness, error screen, graceful shutdown, crash restart, single instance                                                                                                 | M      | Kill the backend → shell recovers; quit → `pgrep` shows no backend/worker; backend failure shows an error screen (test by corrupting the launcher) |
| D5   | Data dir move + copy-migration + pre-migration backup + export                                                                                                                                                      | M      | Existing `~/.nodecraft` DB appears in the new app unchanged; a forced failing migration restores the backup                                        |
| D6   | Logging + Diagnostics dialog                                                                                                                                                                                        | S      | Logs rotate; a failed run's diagnostics bundle contains no secrets (canary test)                                                                   |
| D7   | `.app` + DMG build, ad-hoc signed, icon, About/version                                                                                                                                                              | S      | Installed copy launches from Spotlight, survives quit/relaunch with data intact                                                                    |
| D8   | Developer ID signing + notarization                                                                                                                                                                                 | M      | `spctl -a -vv` accepts; opens on a second Mac without warnings                                                                                     |
| D9   | Auto-update                                                                                                                                                                                                         | M      | Update from vN to vN+1 keeps data; failed update leaves vN working                                                                                 |

## 5. Desktop acceptance tests (automate where possible)

- Saved workflow is present after quit and relaunch (scripted: create via API, quit, relaunch, GET).
- Packaged app starts with no dev server and no network.
- After quit: no `nodecraft-backend`, uvicorn or worker processes remain (`pgrep`), including after `kill -9` of the shell
  (workers self-exit; backend watchdog exits when the shell is gone — add a parent-pid check to the backend too).
- Backend start failure shows the error screen within 25 s with log tail.
- Upgrading across a schema change preserves data and creates a backup.
- Two launches → one window.
- Port already in use → a different port is chosen; no hard-coded 8000 anywhere in the packaged build.

## Implementation status (2026-10-20)

D0–D7 are **done and verified on this Mac** (Tauri 2 shell, bundled python-build-standalone runtime, free port + token,
readiness, supervised restart, graceful shutdown, data-dir copy-migration, pre-migration backups, ad-hoc-signed `.app`).
Lifecycle was checked in the installed app via processes, logs and HTTP (not screenshots). **D8 (Developer ID signing +
notarization) and D9 (auto-update) are not done**: they need a paid Apple Developer account. The Tauri dialog/fs
plugins for native save dialogs are the remaining shell work. Windows/Linux not started.
