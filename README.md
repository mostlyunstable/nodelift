# Nodecraft

Local-first, node-based visual automation IDE. Build workflows on a canvas, write Python code nodes in Monaco,
run them and inspect each node's input, output, logs, errors and timing.

> Code nodes run **unsandboxed** on your machine. See [docs/security.md](docs/security.md).

## Requirements
Python 3.12 (via [uv](https://docs.astral.sh/uv/)), Node 20+, pnpm.

## Run
```bash
make setup   # install backend + frontend deps
make dev     # API on http://127.0.0.1:8000, web on http://localhost:5173
```
Stop with Ctrl+C. Config: copy `.env.example` to `.env`.

## Test
```bash
make check   # ruff, mypy, pytest, tsc, vitest
```

## Layout
`backend/app/{api,domain,engine,runtime}` — FastAPI, contracts, workflow engine, code runner.
`apps/web` — React + React Flow + Monaco editor. Plan: see docs/.

## Status
- M1: code-node runner (`POST /api/v1/nodes/code/test`).
- M2: canvas, Monaco, inspector, test-input and output panels.
- M3 core: validation, sequential dependency-ordered execution, fail-fast.
- M4: SQLite persistence (`~/.nodecraft/nodecraft.db`, override with `NODECRAFT_DATA_DIR`), Alembic migrations applied
  automatically on start, immutable workflow versions (layout changes don't create versions), runs pinned to a version,
  stored per-node input/output/logs/errors, optimistic concurrency on saves (409 on stale revision).
- M5: runs are asynchronous (`POST /workflows/{id}/runs` returns 202). Every run records ordered events
  (`run.started`, `node.started`, `node.finished`, `run.finished`) in `run_events`. Watch live with SSE at
  `GET /runs/{id}/events/stream` (resumes from `Last-Event-ID`/`?after=`), or catch up with `GET /runs/{id}/events?after=N`.
  Runs orphaned by a server crash are closed as failed (`server_restarted`) on startup. The UI shows live node status,
  an event timeline, and falls back to polling if the stream stalls.
- M6: server-side cancel (`POST /runs/{id}/cancel`, idempotent; kills the running node's process, skips the rest, run ends
  `cancelled`). Limits: per-node timeout, whole-run wall-clock budget (`NODECRAFT_MAX_RUN_SECONDS`, default 300),
  concurrent runs (`NODECRAFT_MAX_CONCURRENT_RUNS`, default 4, then HTTP 429), file-size/open-file rlimits per node, memory
  limit (`NODECRAFT_NODE_MEMORY_MB`, **Linux only**: macOS does not enforce it). Retries are opt-in: a node needs
  `config.idempotent: true` plus `config.retry {max_attempts<=5, backoff_ms}`; only runtime errors, timeouts and worker
  crashes are retried, each attempt is its own record. `POST /runs/{id}/resume` starts a new run on the same version that
  reuses already-succeeded nodes (never re-runs them). Worker processes exit by themselves if the server is killed.
- M7: node registry (`GET /nodes/definitions`, generic `POST /nodes/test`), built-in `transform.json` and `http.request`
  nodes, plugin loading via `NODECRAFT_NODE_PLUGINS`. HTTP calls are SSRF-guarded (public addresses only, checked and
  pinned at connect time, no redirects). See [docs/node-authoring.md](docs/node-authoring.md).
- Not yet: node log streaming, container-level isolation (see docs/security.md), credential store, branching, auth,
  Project entity, Postgres/hosted deployment adapters.
- Monaco loads its editor files from a CDN, so the first load needs internet access.

## Database migrations
```bash
cd backend && uv run alembic revision --autogenerate -m "describe change"
```
A test fails if the models and migrations drift apart.
