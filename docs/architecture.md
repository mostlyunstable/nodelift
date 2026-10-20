# Architecture

Nodecraft is a local-first visual automation IDE: a React editor, a FastAPI backend that owns all state and
execution, and (on macOS) a Tauri shell that packages both. Decisions and their reasons are in [adr/](adr/README.md).

```
Nodecraft.app (Tauri)  ──spawns──▶  Python runtime  ──serves──▶  FastAPI  ◀──fetch/SSE──  React UI (webview)
                                                                    │
                                    api → services → engine/nodes ──┴─▶ runtime (worker subprocess)
                                              └──▶ storage (SQLite, keychain)
```

## Backend layers (`backend/app`, enforced by import-linter)

| Layer              | Responsibility                                                                 | May import                  |
| ------------------ | ------------------------------------------------------------------------------ | --------------------------- |
| `domain`           | Models, validation, ports/protocols, errors, migrations of the workflow format | nothing else in the app     |
| `engine`           | Planner and executor: ordering, branching, retries, cancel, budgets, redaction | `domain`                    |
| `nodes`, `runtime` | Node implementations and registry; subprocess worker, net guard                | `domain`, `engine`          |
| `services`         | Use cases: run lifecycle, versions, resume, prune, run hub, execution gate     | `domain`, `engine`, `nodes` |
| `storage`          | SQLAlchemy repositories, Alembic migrations, backups, secret stores            | `domain`                    |
| `api`              | HTTP only: routing, security middleware, error mapping, SSE                    | everything below            |

`main.py` and `services/container.py` are the composition roots.

## Key flows

- **Run:** `POST /workflows/{id}/runs` → snapshot draft into an immutable version → run pinned to it → executor emits
  events → `RunRecorder` persists node results and events → `RunHub` wakes SSE streams.
- **Resume:** new run on the current draft; reuse earlier successes whose type, config and input are unchanged.
- **Secrets:** `{{credential:NAME}}` resolved at execution; values masked from outputs, logs, errors and events.
- **Import/export:** versioned JSON with a preview step; nothing runs on import.
- **Startup:** back up database → migrate → recover runs left `running` by a crash.

## Frontend (`apps/web/src`)

`state/store.ts` (Zustand) holds the editor: graph, autosave and dirty state, undo/redo, dialogs. `canvas/mapper`
converts between React Flow and the workflow format. `api/` is a typed client over generated OpenAPI types plus a
`fetch`-based SSE reader. `desktop/` talks to the Tauri shell when present. Types in `api.generated.ts` are generated
from `docs/api/openapi.json`; CI fails if either drifts.

## Process lifecycle (desktop)

Random loopback port and token per launch → readiness polling → supervised restart (max 3) → parent-pid watchdog in the
backend → graceful `/system/shutdown`, then SIGTERM, then SIGKILL.

## Not built

Sandboxed execution, hosted/multi-user mode, Postgres, scheduling/triggers, parallel node execution, Windows/Linux
shells, Developer ID signing, notarization, auto-update.
