# Nodecraft

Local-first, node-based visual automation IDE. Build workflows on a canvas, write Python code nodes in Monaco,
run them and inspect each node's input, output, logs, errors and timing.

> On macOS, code nodes are confined by the OS (no network unless enabled, no home-folder access, temp-folder writes only). Elsewhere they run with your permissions. See [docs/security.md](docs/security.md).

## Requirements
Python 3.12 (via [uv](https://docs.astral.sh/uv/)), Node 20+, pnpm.

## Run
```bash
make setup   # install backend + frontend deps
make dev     # API on http://127.0.0.1:8000, web on http://localhost:5173
```
Stop with Ctrl+C (or `make stop`). Config: copy `.env.example` to `.env`.
`make dev` generates a random API token shared by the API and the dev proxy.

## Test
```bash
make check          # ruff, mypy, import-linter, pytest, tsc, eslint, vitest
cd apps/web && pnpm e2e   # Playwright end-to-end (E2E_NETWORK=1 adds the real-GitHub specs)
```

## Desktop app (macOS)
```bash
make app           # builds the bundled runtime + Nodecraft.app (ad-hoc signed)
make install-app   # copies it to /Applications
scripts/check_installed_app.sh   # launches it and checks the backend, schema, signature and clean quit
```
Data lives in `~/Library/Application Support/Nodecraft` (an existing `~/.nodecraft` database is copied, never moved).
This build is for this Mac. To give it to anyone else you need a Developer ID and notarization, which needs a paid Apple
Developer account: put the four `APPLE_*` values listed at the top of `scripts/release.sh` in the environment and run it; it
signs, notarizes and produces a `.dmg` that opens without a warning.

If `git` or `python3` print "You have not agreed to the Xcode license", run `sudo xcodebuild -license accept` once. Until
you do, Nodecraft's *Run a command* feature (which uses the system Python) and the confinement tests fail.

## Layout
`backend/app/{domain,engine,nodes,runtime,services,storage,api}` — layered backend (see [docs/architecture.md](docs/architecture.md)).
`apps/web` — React + React Flow + Monaco editor; `apps/web/src-tauri` — desktop shell. Decisions: [docs/adr](docs/adr/README.md).

## What works
- Canvas editor with autosave, undo/redo, command palette (⌘K), shortcuts, light/dark theme, a guided "Debug me" example.
- Nodes: Python code, JSON transform, HTTP request, branch, filter list, text/HTML template, CSV, read/write file and SQLite query (confined to
  `<data folder>/files`), and Ask Claude (key from a saved credential); plugin nodes ([docs/node-authoring.md](docs/node-authoring.md)).
- Branching by output ports, fail-fast, cancel, retries (opt-in), run budgets, resume from failure.
- SQLite persistence, immutable versions, run history, live events over SSE with recovery, pre-migration backups.
- Import/export with preview; credentials in the system keychain, masked in all results.
- Triggers: a workflow can run on a schedule (every N minutes, or daily at a time; only while Nodecraft is open) or from a
  private webhook address on this computer (*⋯ → Triggers*).
- Repository Explorer (R2): paste a GitHub URL (private repositories and 5,000 requests an hour with a token saved under *GitHub access*), press *Show Nodes*, browse the files at a pinned commit and read them
  in a read-only editor. Python, JavaScript/TypeScript, HTML, CSS, Go, Java, Rust, Ruby, shell, Markdown, YAML, JSON and SQL are analysed statically (nothing is run) and
  their resolved imports, links and calls are drawn as dependency edges with confidence ([plan](docs/explorer/PLAN.md)).
- Local API protection: Host/Origin checks and a per-launch bearer token ([docs/security.md](docs/security.md)).

## Limits (read these)
- Code-node confinement uses macOS Seatbelt (deprecated by Apple, not a VM); Linux/Windows have none yet.
- Notarization needs your Apple Developer account (see above); there is no auto-update, licensing or payment yet; no Windows/Linux builds.
- Schedules do not run while the app is closed and missed runs are not made up. No parallel execution, hosted mode or Postgres.
- Browser end-to-end tests (Playwright, with axe) cover the interface; the native window itself is verified by logs and HTTP, not screenshots.

## Database migrations
```bash
cd backend && uv run alembic revision --autogenerate -m "describe change"
```
A test fails if the models and migrations drift apart.
