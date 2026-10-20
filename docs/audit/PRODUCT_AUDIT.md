# Nodecraft product audit

Audit date: 2026-10-18. Repo: `~/nodecraft` (git root), `main` at `4ec6651`, clean and identical to `origin/main`
(github.com/mostlyunstable/nodelift). Nothing was changed in application code during this audit.

How to read this: every claim names its evidence. **Measured** = I ran it. **Source** = read in code, not executed.
**Not verified** = no evidence either way. Related documents: [MILESTONE_STATUS](MILESTONE_STATUS.md),
[ARCHITECTURE_REVIEW](ARCHITECTURE_REVIEW.md), [DESKTOP_APP_PLAN](DESKTOP_APP_PLAN.md), [UI_UX_AUDIT](UI_UX_AUDIT.md),
[SECURITY_REVIEW](SECURITY_REVIEW.md), [ROADMAP](ROADMAP.md).

## Executive summary

**What has actually been built.** A working local web app: a React Flow canvas, Monaco code editor and inspector
(`apps/web`, ~1.2k lines) over a FastAPI + SQLite backend (`backend/app`, ~2.5k lines) with a node registry
(Python code, JSON transform, HTTP request), a sequential execution engine, async runs with persisted events and SSE
streaming, cancel, limits, opt-in retries, resume-from-failure, and Alembic migrations. About 1.5k lines of tests (1.3k backend, 0.3k frontend).

**What works end to end (measured).** Create workflow → run → watch live status → inspect per-node input/output/logs/
errors → cancel → resume; data survives a server restart; a run is pinned to the saved version. `make check` passes:
ruff, mypy (36 files), 120 backend tests (1 skipped, Linux-only), tsc, 18 frontend tests. Backend line coverage is 92%
(`pytest --cov`). A 40-node chain runs in 0.9 s (19 ms/node). A 300-node workflow opens in ~190 ms; node selection
takes ~30 ms (dev build, WebKit browser pane).

**What is broken, incomplete or unverified.**

- BROKEN: run/event timestamps are naive UTC on read, so the UI shows UTC as local time (5½ h off in this environment).
- BROKEN: the legacy `POST /runs` and `POST /nodes/*` endpoints bypass the concurrency limit and run budget (8/8
  parallel requests accepted; stored runs correctly return 429 after 4).
- BROKEN: reloading the page or clicking _New_/_Open_ silently discards unsaved edits; there is no dirty indicator,
  autosave or draft recovery (verified in the browser).
- MISSING: conditional branching, versions UI (view/diff/restore), workflow import/export, credentials, templates,
  undo/redo, command palette, onboarding, settings/log viewer, ESLint/Prettier, CI, ADRs.
- UNVERIFIED: offline behaviour (Monaco loads from jsDelivr), Postgres, behaviour with >500 events per run, event-loop
  blocking under load, the plugin-node UI path in a browser, any desktop packaging.

**Three biggest technical risks.**

1. The API executes code but trusts any local caller: no auth token, `Host` header not validated (`Host: evil.example`
   returned 200), so DNS rebinding is a credible path from a web page to code execution. Cross-site POST is blocked
   today (text/plain rejected with 422; JSON preflight returns 405) — that protection is accidental, not designed.
2. Packaging: the backend assumes a source checkout and a normal Python install (`sys.executable -I worker_entry.py`,
   `BACKEND_DIR`-relative Alembic paths, `uvicorn reload=True`). A naive PyInstaller bundle would break workers, and
   would also lack the stdlib that user code needs.
3. Trust model: user code is unsandboxed by design (it can read the app database — measured). Fine for a local dev
   tool, but every hosted/shared scenario needs a different architecture, and the UI currently gives no hint of it.

**Three biggest UX problems.**

1. Lost work: no dirty state, autosave, or "reopen last workflow"; the app starts blank every time.
2. The workspace doesn't guide: blank first-run canvas, an 11-control toolbar that clips below ~900 px, and three
   fixed panes (440 px inspector + 280 px bottom dock) that leave the canvas small.
3. Debugging stops short of its promise: errors don't navigate to the failing line or node, there is no logs/problems
   view, run history can't show which version or input produced a run, and versions are invisible.

**What to do next.** P0 fixes (≈1 week): API auth + Host/Origin checks, route every execution through one limiter,
timestamp fix, unsaved-changes safety, `reload` off by default. Then the desktop shell (spike first). Order and
acceptance criteria are in [ROADMAP](ROADMAP.md).

**Recommended path to a macOS release.** Tauri 2 shell + a bundled Python runtime sidecar (not a frozen exe), random
loopback port + per-launch token, data in `~/Library/Application Support/Nodecraft`, bundled Monaco, a 1–2 day spike
before committing (this Mac has no Rust, no full Xcode and no Developer ID). Locally built, ad-hoc-signed `.app` first;
signing/notarization/auto-update only after an Apple Developer account exists. Details in
[DESKTOP_APP_PLAN](DESKTOP_APP_PLAN.md).

## Repository inventory

### Modules (all paths under `~/nodecraft`)

| Module                               | Responsibility                                                                                                                                                                        | Evidence                                          |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| `backend/app/api/v1/*`               | HTTP routes, validation, error envelope. `stored.py` = workflows/versions/runs/events/SSE; `nodes.py` = definitions + single-node test; `workflows.py` = validate + legacy ad-hoc run | route code; OpenAPI paths probed                  |
| `backend/app/domain/*`               | Pydantic models + Protocols: workflow format and validation (`workflow.py`), node contract and registry (`nodes.py`), run records, repository interfaces                              | no `fastapi`/`sqlalchemy` import (grep, measured) |
| `backend/app/engine/executor.py`     | Topological order, data passing, fail-fast, retries, cancel, run budget, resume reuse                                                                                                 | 94% covered                                       |
| `backend/app/nodes/*`                | `code.python`, `transform.json`, `http.request`; `default_registry()`, plugin loader                                                                                                  | tests in `test_nodes.py`                          |
| `backend/app/runtime/*`              | `SubprocessRunner` (worker process, rlimits, kill group), `worker_entry.py`, `net_guard.py` (SSRF)                                                                                    | tests with real pid checks                        |
| `backend/app/services/*`             | `WorkflowService` (snapshot, start/cancel/resume run), `RunHub` (SSE wake-ups, live-run table)                                                                                        |                                                   |
| `backend/app/storage/*`              | SQLAlchemy models, repositories, engine/PRAGMAs, Alembic runner; 3 migrations                                                                                                         | `test_migrations_match_models`                    |
| `apps/web/src/state/store.ts`        | Single Zustand store: editor state, server sync, run following (371 lines)                                                                                                            | source                                            |
| `apps/web/src/canvas/mapper.ts`      | React Flow state ⇄ backend workflow format                                                                                                                                            | `mapper.test.ts`                                  |
| `apps/web/src/{panels,nodes,editor}` | Inspector + per-type config editors, node card, JSON field, run panel                                                                                                                 |                                                   |

### How the frontend talks to the backend

Browser → `fetch('/api/v1/...')` (relative URL) → Vite dev proxy (`vite.config.ts`, hard-coded `127.0.0.1:8000`) →
FastAPI. Live runs use `EventSource('/api/v1/runs/{id}/events/stream')` plus a 4 s status poll as a watchdog
(`state/store.ts`, `api/events.ts`). There is no production serving path: FastAPI does not serve the built frontend.

### Workflow from editor to execution

1. Canvas edits live only in the Zustand store (`FlowNode[]`, `Edge[]`).
2. _Run workflow_ → `store.runWorkflow` → `save()` (create or `PUT` with `revision`) → `POST /workflows/{id}/runs`.
3. `WorkflowService._launch`: snapshot the draft into an immutable version (deduplicated by content hash, layout
   excluded), validate against the registry, enforce the 4-run cap, create the run row, start an asyncio task.
4. `execute_workflow`: topological order → per node `registry.get(type).execute(...)` (code nodes spawn a worker
   process) → observer persists each node execution and an event → `RunHub` wakes SSE streams.
5. Final status written, `run.finished` emitted, the UI fetches the final run.

### Where data lives

SQLite at `~/.nodecraft/nodecraft.db` (WAL): `workflows` (draft JSON + revision), `workflow_versions` (immutable
snapshots), `runs`, `node_executions` (input/output/logs/error per attempt), `run_events`. Nothing else is persisted:
no settings, no UI state, no logs on disk (uvicorn logs to stdout only). Evidence: `storage/models.py`; the directory
listing of `~/.nodecraft`.

### Feature reality check

| Feature                                          | State                                                                                        | Evidence                                                             |
| ------------------------------------------------ | -------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| Python code node, test with input                | Real                                                                                         | `/nodes/test`, tests, browser                                        |
| JSON transform, HTTP node                        | Real. HTTPS works and rejects an expired certificate (measured once, not in automated tests) | `test_nodes.py`; manual run against example.com / expired.badssl.com |
| Save/open/versions                               | Save and open real. Versions are created but cannot be viewed or restored in the UI          | `listVersions` only feeds the "Publish (vN)" label                   |
| Run history, events, resume                      | Real                                                                                         | tests, browser                                                       |
| Conditional branching                            | **Missing** (an original M3 goal)                                                            | no branch node, no `activated_ports` logic                           |
| Ports                                            | Declared in `NodeDefinition`, **not enforced** (`port: "NOPE"` validates)                    | measured                                                             |
| Schema migration for workflow JSON               | **Missing**; `schema_version` is `Literal[1]` and a v2 file yields a generic 422             | measured                                                             |
| Credentials, import/export, templates            | Missing                                                                                      | grep                                                                 |
| Frontend lint/format, CI, ADRs, architecture doc | Missing (`.github/` absent; no eslint/prettier binaries)                                     | filesystem                                                           |

### Unnecessary complexity / tight coupling

See [ARCHITECTURE_REVIEW](ARCHITECTURE_REVIEW.md). Short version: two parallel run entry points, `services` importing
from `api`, `api` constructing storage repositories, a god-store on the frontend, and hand-duplicated API types.
