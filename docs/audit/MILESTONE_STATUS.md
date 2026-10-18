# Milestone status (M0–M7), evidence-based

Audit date 2026-10-18, `main@4ec6651`. Status key: VERIFIED (code + meaningful tests or direct execution),
PARTIAL, UNVERIFIED, MISSING, BROKEN. "Measured" = I executed it during this audit. Earlier "done" claims were not
trusted; each row was re-checked.

Baseline evidence (measured, fresh run): `make check` → ruff clean, mypy clean (36 files), **120 passed / 1 skipped**
backend, tsc clean, **18 passed** frontend. Backend coverage **92%** (`pytest --cov=app`; `worker_entry.py` shows 0%
only because it runs in a child process; `__main__.py` 0%). Frontend coverage not measured (no coverage plugin
installed). No CI exists, so these results are reproducible only by running `make check` locally.

## Matrix

| Milestone | Status | Evidence | Problems | Required action |
|---|---|---|---|---|
| **M0** Assessment & architecture | **PARTIAL** | Layers exist and `domain/` + `engine/` import no web/DB code (grep). `README.md`, `docs/security.md`, `docs/node-authoring.md` exist | The architecture plan lives outside the repo (`~/.claude/plans`); no `docs/architecture.md`, no ADRs, no import-linter (planned, never added). `services/workflow_service.py` imports `app.api.errors`; `api/v1/stored.py` imports `app.storage.repositories` | Add architecture doc + ADRs; enforce boundaries with import-linter; fix the two layering leaks (P2) |
| **M1** Code node | **VERIFIED** (with caveats) | `test_code_runner.py` covers success, syntax error (line), missing main, runtime error with trimmed traceback, invalid/NaN output, 5 MB cap, env scrubbing, timeout kills the real pid; API returns 200 + structured error, 422 for bad request | Memory limit only enforced on Linux; docs say so. Worker needs the full stdlib at runtime (matters for packaging) | None for M1 itself; see packaging risk in [DESKTOP_APP_PLAN](DESKTOP_APP_PLAN.md) |
| **M2** Visual editor | **PARTIAL** | Measured in browser: add node, connect, edit name, run, per-node status. Mapper round-trip tests. 300-node workflow opens in ~190 ms | Node **deletion** relies on React Flow's key handler and is untested by me and by any test. **No connection validation** (`onConnect` accepts self-loops/cycles; backend rejects only at validate/run). No undo/redo, no copy/paste, no dirty indicator, canvas lost on reload (measured). Toolbar clips below ~900 px (screenshot) | Connection validation, autosave/dirty, undo/redo, responsive toolbar (P0/P2) |
| **M3** Connected execution | **PARTIAL** | `test_workflow_engine.py` + `test_storage_api.py`: chain passes data, fan-in keyed by node id, fail-fast skips downstream, cycle/dangling detection; 40-node chain 0.9 s (measured) | **Conditional branching MISSING** (explicit M3 goal). Ports declared but not enforced: `port:"NOPE"` → `valid:true` (measured). All entry nodes receive the same run input. Strictly sequential | Decide: implement branch node (P3) or remove from the goal; enforce ports when branching lands |
| **M4** Persistence & versioning | **PARTIAL** | Restart persistence test + manual restart (measured); `test_migrations_match_models`; runs pinned to a version (`test_run_is_pinned_...`); 409 on stale revision | **BROKEN:** GET returns naive UTC timestamps (`…17:05:56.750041` vs create's `…Z`), UI renders UTC as local. No workflow-format migration framework (`schema_version` is `Literal[1]`; v2 → generic 422). Versions can't be viewed/restored/diffed in the UI; "Publish" is nearly redundant because every run auto-snapshots. No saved-vs-unsaved indicator. No backup | Timestamp fix (P0); dirty/autosave (P0); version UI + migration framework (P2); backups (P1) |
| **M5** Debugging & observability | **VERIFIED** for the core, **PARTIAL** overall | `test_run_events.py`: ordered persisted events, catch-up `?after=`, SSE with `Last-Event-ID`, partial run visible while running, orphan runs closed on startup. Browser (measured): live running→succeeded, timeline, recovery after killing the API mid-run | Logs appear only when a node finishes (no streaming). `GET /events` silently caps at 500 (latent: needs retries to exceed 200-node runs; not reproduced). No run comparison, no filtering, no link from error to code line, run history lacks input/version detail. Timestamp bug affects history | Pagination + truncation flag; error→line/node navigation; log tab (P2) |
| **M6** Reliability & security | **PARTIAL** | `test_reliability.py` (with pid-based checks after I found and fixed vacuous `pgrep` assertions earlier): cancel kills worker, orphan worker exits when parent is SIGKILLed, run wall-clock budget, concurrent cap → 429, retries only for idempotent nodes, resume reuses outputs and never re-runs them, crash→resume | **BROKEN:** `POST /runs` and `POST /nodes/test|code/test` ignore the concurrency cap and run budget (8/8 accepted, measured). Weak tests remain: file-size limit asserts only "failed"; memory-limit test skipped on macOS. No API auth / Host check (see SECURITY_REVIEW). No secrets handling exists (nothing to leak yet, but run inputs/outputs/http bodies are stored unredacted). Isolation is none, by design and documented | Single execution gate (P0); auth + Host allowlist (P0); redaction/credentials (P3) |
| **M7** Extensibility & hosting readiness | **PARTIAL** | Registry + plugin loader tested (plugin node runs in a workflow); `GET /nodes/definitions`; `docs/node-authoring.md`; SSRF unit tests; HTTPS verified manually (works, rejects expired cert) | HTTPS path has no automated test. Adding a node needs no engine changes, but the UI shows a raw JSON editor unless a per-type form is added (plugin UI path not exercised in a browser). Contracts: only the `/api/v1` prefix; no `type_version`, no workflow migrations, no OpenAPI→TS types (frontend types hand-copied). Hosting: SQLite only — Postgres **never run**; no auth; no Project/CredentialReference entities | Treat "hosting ready" as **planned, not done**. Postgres CI job, auth, API codegen (P2/P3) |

## Post-P0 update (2026-10-18)
Resolved since this matrix was written: **BUG-1** (timestamps), **BUG-2** (reloader), **SEC-1** (Host/Origin/token),
**SEC-2** (limits bypass), **DL-1** and **DL-2** (unsaved work), and the untested HTTPS path. M4 timestamps and M6
limits are no longer BROKEN; M2/M4 "unsaved changes" gaps are closed. Still open: everything else in the matrix
(branching, version UI, format migrations, connection validation, undo/redo, credentials, desktop packaging). See the
completion report in [ROADMAP](ROADMAP.md). Counts: 157 backend tests (1 skipped), 36 frontend tests.

## Issue register (as of the audit, before P0)

Severity: S1 critical, S2 high, S3 medium, S4 low. Impact = who is hurt. Confidence = how sure I am it is real.
Effort: S ≤ 1 day, M ≈ 2–4 days, L ≈ 1–2 weeks, XL > 2 weeks.

### Critical bugs (functional)
| ID | Issue | Sev | Impact | Confidence | Effort | Evidence |
|---|---|---|---|---|---|---|
| BUG-1 | Naive-UTC timestamps shown as local time | S3 | Every user; confusing history | High (measured) | S | API output without `Z`; `RunPanel.tsx:37` `new Date(created_at)`; screenshots showed 16:xx at ~22:xx local |
| BUG-2 | `python -m app` always runs uvicorn `reload=True`; killing the parent leaves the reloader child holding the port | S3 (S2 for desktop) | Dev now, desktop later (port clash, orphan process) | High (happened twice) | S | `__main__.py:8` |
| BUG-3 | Workflows over 200 nodes save and open but cannot run; UI gives no early warning | S4 | Large-graph users | High (422 measured on 300 nodes) | S | `MAX_NODES` in `domain/workflow.py` |
| BUG-4 | `GET /runs/{id}/events` returns ≤500 events with no truncation marker | S4 | Large/retry-heavy runs; UI timeline would be incomplete | Medium (code) | S | `list_events(..., limit=500)` |
| BUG-5 | Edge ports not validated | S4 | Future branching | High (measured) | S | validate returned `valid:true` |
| BUG-6 | Self-loop/cycle connections allowed in the canvas | S3 | Editing UX | High (source) | S | `store.ts` `onConnect` |

### Data-loss risks
| ID | Issue | Sev | Confidence | Effort |
|---|---|---|---|---|
| DL-1 | Unsaved canvas lost on reload/quit/crash; app starts blank; no dirty flag or draft recovery | **S2** | High (measured) | M |
| DL-2 | *New* and *Open* replace the canvas without confirmation (`onClick={s.reset}`, `store.open`) | S3 | High (source) | S |
| DL-3 | No database backup/export; hard `DELETE /workflows/{id}` cascades to runs (no UI for it today) | S3 | High (source) | M |
| DL-4 | Opening the app from a different data dir or a second window can fork state; only a 409 message on conflict | S4 | Medium | M |

### Security risks (details in [SECURITY_REVIEW](SECURITY_REVIEW.md))
| ID | Issue | Sev | Confidence | Effort |
|---|---|---|---|---|
| SEC-1 | No API auth; `Host` header not validated → DNS-rebinding route to code execution | **S2** | High that the precondition holds; exploit not demonstrated | S |
| SEC-2 | Execution limits bypassed via legacy/ad-hoc endpoints | S3 | High (measured) | S |
| SEC-3 | User code can read the app DB and any user-readable file, and use the network (trusted mode) | S2 if hosted / accepted locally | High (measured) | XL to fix properly |
| SEC-4 | Inputs, outputs, HTTP bodies and headers stored in plain text; no redaction or credential store | S3 | High (source) | L |
| SEC-5 | Plugins run in-process with full privileges | S4 (operator-only) | High | — |

### Architectural weaknesses
See [ARCHITECTURE_REVIEW](ARCHITECTURE_REVIEW.md): ARCH-1 layering leaks, ARCH-2 duplicate execution paths,
ARCH-3 frozen-path assumptions, ARCH-4 sync DB calls on the event loop (unverified impact), ARCH-5 god store,
ARCH-6 duplicated API types, ARCH-7 no composition root.

### Missing product features
Branching, version browser, import/export, templates, credentials, subflows, undo/redo, command palette, node search,
settings, log viewer, onboarding, autosave, keyboard shortcuts, scheduling.

### Cosmetic / usability
Toolbar overload and clipping (<900 px), blank empty canvas, inconsistent button hierarchy, "Publish" naming,
validation issues shown as small text in the bottom-left pane, no light theme, no focus styles, minimap visible when
empty. Full list in [UI_UX_AUDIT](UI_UX_AUDIT.md).
