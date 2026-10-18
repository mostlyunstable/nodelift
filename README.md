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
- M1 done: code-node runner (`POST /api/v1/nodes/code/test`).
- M2 done: canvas, Monaco, inspector, test-input and output panels.
- M3 core done: `POST /api/v1/workflows/validate`, `POST /api/v1/runs` (sequential, dependency order, fail-fast).
- Not yet: server-side persistence/versioning (workflows save to browser localStorage), live streaming, server-side cancel, branching, retries, sandboxing.
- Monaco loads its editor files from a CDN, so the first load needs internet access.
