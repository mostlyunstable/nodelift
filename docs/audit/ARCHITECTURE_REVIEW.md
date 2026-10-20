# Architecture review

Audit date 2026-10-18, `main@4ec6651`. Evidence is from source reading unless marked "measured".

## Current architecture (as built)

```
apps/web (React, Zustand, React Flow, Monaco)
   │  fetch /api/v1 (relative; Vite proxy → 127.0.0.1:8000)   EventSource + 4s status poll
   ▼
backend/app/api/v1  ── thin routes, AppError envelope
   ▼
services/WorkflowService + RunHub     (snapshot, start/cancel/resume, SSE wake-ups, live-run table)
   ▼                    ▼
engine/executor    storage/repositories (SQLAlchemy, SQLite WAL)  ◄── domain/repositories (Protocols)
   ▼
domain/nodes (NodeRegistry) ──► nodes/builtin/{code.python, transform.json, http.request}
   ▼
runtime/SubprocessRunner → worker_entry.py (child process, rlimits, process group)
runtime/net_guard (SSRF)
```

What is good and should be kept:

- `domain/` and `engine/` import no FastAPI/SQLAlchemy (grep measured) and the engine takes a registry and an observer
  — it is testable without HTTP or a database.
- Repository Protocols + a SQL implementation; migrations are checked against the models by a test.
- Events are persisted before they are announced; SSE correctness never depends on the in-process hub.
- Node contract is small (`validate_config`, `execute`, a definition); a plugin node runs in a workflow in a test.
- Layout is excluded from the content hash, so moving a node never creates a version.

## Weaknesses and recommended changes

| ID      | Finding                                                                                                                                                                                                      | Evidence                                                       | Impact                                                                              | Recommendation                                                                                                                               | Effort |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------- | ----------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| ARCH-1  | Layer leaks: `services/workflow_service.py` imports `app.api.errors.AppError`; `api/v1/stored.py` imports `app.storage.repositories` and builds repos per request                                            | grep (measured)                                                | Services can't be reused outside HTTP; swapping storage touches the API layer       | Move `AppError` to `domain/errors.py`; build services in a composition root (`main.py`/`deps.py`) and inject; add import-linter contracts    | S      |
| ARCH-2  | Two execution entry points: stored runs (`POST /workflows/{id}/runs`) and legacy ad-hoc `POST /runs`; plus `POST /nodes/test`, `/nodes/code/test`. Only the first applies the concurrency cap and run budget | measured: 8/8 parallel accepted on the others                  | Security/limits bypass; duplicated logic                                            | One `ExecutionGate` (cap, budget, cancel registry) used by every path; delete or deprecate `POST /runs` (the UI doesn't use it)              | S      |
| ARCH-3  | Frozen/packaged-runtime assumptions: worker spawned via `sys.executable -I <path>/worker_entry.py`; Alembic located via `BACKEND_DIR` (`parents[2]`); `uvicorn.run(reload=True)`; data dir `~/.nodecraft`    | `subprocess_runner.py:21,95`, `storage/db.py:8`, `__main__.py` | Packaging breaks silently; see DESKTOP_APP_PLAN                                     | Resolve resources with `importlib.resources`; make the worker command and data dir configuration; reload only behind a dev flag              | M      |
| ARCH-4  | Synchronous SQLAlchemy calls run on the asyncio loop (`RunRecorder`, repositories called from async routes/tasks)                                                                                            | `services/workflow_service.py`                                 | Slow disk could stall SSE and runs. **Unverified**: 40- and 200-node runs were fine | Measure p99 loop lag under 4 concurrent runs + 10 SSE clients; if bad, `run_in_threadpool` the recorder or move to async SQLAlchemy          | M      |
| ARCH-5  | Frontend god-store: `state/store.ts` (371 lines) mixes canvas state, server sync, SSE following, run state and messages; module-level `stopFollowing`                                                        | source                                                         | Hard to test/extend (undo/redo, autosave, dirty state all need to cut across it)    | Split: `editorStore` (graph, selection, dirty, undo), `runStore` (run/events/follow), `serverStore`/TanStack Query for lists                 | M      |
| ARCH-6  | API types hand-duplicated in `apps/web/src/types/workflow.ts`                                                                                                                                                | source                                                         | Silent drift when the backend changes                                               | Generate with `openapi-typescript` from `/openapi.json`; fail CI on diff                                                                     | S      |
| ARCH-7  | Contract versioning is only the `/api/v1` path. Workflow `schema_version` is `Literal[1]`; nodes lack `type_version`; unknown newer version gives a generic Pydantic 422                                     | measured                                                       | Old files can't be migrated; new files can't be rejected helpfully                  | Add `domain/migrations.py` (dict→dict chain), a clear `unsupported_schema_version` error, `type_version` on nodes before import/export ships | M      |
| ARCH-8  | Ports are declared in `NodeDefinition` but never enforced; edges accept any port string                                                                                                                      | measured                                                       | Branching will be built on sand                                                     | Validate edge ports against definitions in `validate_workflow`                                                                               | S      |
| ARCH-9  | Settings are read via `lru_cache` _and_ copied onto `app.state`; `create_app(settings=...)` for tests                                                                                                        | `config.py`, `main.py`                                         | Minor confusion                                                                     | Single source: `app.state.settings` only                                                                                                     | S      |
| ARCH-10 | Event payloads are untyped dicts; the UI branches on strings                                                                                                                                                 | `RunEvent.payload`                                             | Typos not caught                                                                    | Pydantic discriminated union for event types (also yields TS types)                                                                          | S      |

## Unnecessary complexity (things _not_ to build yet)

- Postgres, queues, Kubernetes, multi-user auth — none is needed for a desktop product. Keep the repository boundary,
  skip the infrastructure.
- A second runtime (container worker) before the desktop shell exists.
- Parallel execution: the planner is level-ready, but sequential is 19 ms/node; parallelism adds failure modes with
  no demonstrated need.

## Target architecture for the desktop product

Same backend, three additions: an **execution gate**, a **runtime configuration object** (data dir, port, token,
python path, worker command) and **auth middleware** (token + Host/Origin allowlist). The shell (Tauri) owns the
process lifecycle; the frontend receives `{baseUrl, token}` at startup instead of assuming a Vite proxy. See
[DESKTOP_APP_PLAN](DESKTOP_APP_PLAN.md).

## Recommended order

1. ARCH-2 (gate) and ARCH-1 (layering) — small, remove a security hole and make later work cheaper.
2. ARCH-3 (frozen-safe paths) — prerequisite for packaging.
3. ARCH-5/6 — before adding undo/redo, autosave and versions UI.
4. ARCH-7/8 — before import/export or branching.
