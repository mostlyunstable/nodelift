# Roadmap

Audit date 2026-10-18, based on `main@4ec6651`. Effort: S ≤ 1 day, M 2–4 days, L 1–2 weeks, XL > 2 weeks (one developer).
Risk: how likely the change breaks something existing. Each task lists acceptance criteria and how to verify. IDs refer
to [MILESTONE_STATUS](MILESTONE_STATUS.md), [SECURITY_REVIEW](SECURITY_REVIEW.md) and
[ARCHITECTURE_REVIEW](ARCHITECTURE_REVIEW.md).

**Recommended order:** P0 (all) → D0 spike → P1 (D1–D7) in parallel with the P2 trust items (autosave, error→line) →
rest of P2 → D8/D9 once a Developer ID exists → P3 selectively.

---

## P0 completion report (2026-10-18)

All six P0 tasks are implemented, each with tests that I checked can fail (mutation checks noted). Details below the
original task text. Evidence: `make check` → ruff + mypy clean, **157 backend tests passed / 1 skipped** (was 120),
**36 frontend tests passed** (was 18), tsc clean. Verified manually through `make dev` and the browser.

| Task                    | Result                                                                                                                                                                                                                                                                            | Evidence                                                                                                                                                                                 |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| P0-1 API gatekeeping    | **Done.** Host allowlist (403), Origin allowlist (403), optional bearer token on every route except `/health` (401), constant-time compare, docs/OpenAPI protected too; a non-loopback bind now also requires a token. `make dev` generates a token and the Vite proxy injects it | `tests/test_security.py` (route sweep over every OpenAPI path); live: no token → 401, `Host: evil.example` → 403, foreign Origin via proxy → 403, proxy with token → 200                 |
| P0-2 One execution gate | **Done.** `ExecutionGate` caps runs and single-node tests; `POST /runs` removed (now 404); slots released on every exit path                                                                                                                                                      | 8-parallel probe previously 8/8 accepted; tests assert 429 for `/nodes/test` and `/nodes/code/test`, slot release after success/422/user-code failure                                    |
| P0-3 Timestamps         | **Done.** `UTCDateTime` column type; every API timestamp is explicit UTC; rows written before the fix read correctly as UTC                                                                                                                                                       | `tests/test_timestamps.py` (all endpoints, legacy naive rows, non-UTC input); browser: history showed `22:51:44` at local `22:51:47` (before: 17:xx)                                     |
| P0-4 Never lose edits   | **Done.** Dirty tracking, 1.5 s debounced autosave, Saved/Saving/Unsaved/Save failed indicator, last workflow restored on launch, flush-before-New/Open with a confirm only when saving fails, `beforeunload` prompt, save on tab hide, conflict stops autosave                   | 15 store/App tests (races, failures, conflicts, throwing localStorage); 3 mutation checks each made a test fail; browser: edit → "Unsaved" → "Saved" in 2.6 s → reload restored the node |
| P0-5 Dev lifecycle      | **Done.** No reloader unless `NODECRAFT_RELOAD=1`; `make stop`                                                                                                                                                                                                                    | `tests/test_dev_server.py`; I reproduced the old bug (port still open after killing the parent with reload on) and confirmed the default no longer has it                                |
| P0-6 HTTPS tests        | **Done.** Local TLS server with a throwaway CA                                                                                                                                                                                                                                    | `tests/test_https.py`: trusted cert succeeds, name verified against the URL host (not the pinned IP), untrusted cert rejected, guard still blocks private addresses over TLS             |

Known limits of the P0 work: the token is optional in plain `make dev-api` (Host/Origin checks still apply); SSE cannot
carry an Authorization header, so token-protected deployments rely on the dev proxy for now (fetch-based SSE is task D2);
autosave creates a workflow on the first node, so abandoned "Untitled" workflows can accumulate until a delete UI exists.

## P0 — Must fix (original task text)

### P0-1 Authenticate and scope the API (SEC-1) — S/M, risk low

- **Problem / impact:** any local caller, including a DNS-rebinding page, can execute code (`Host: evil.example` → 200, measured).
- **Implementation:** `TrustedHostMiddleware` (127.0.0.1/localhost); reject present-but-unlisted `Origin`; bearer token
  from `NODECRAFT_API_TOKEN` (generated and passed by the shell in desktop mode; in dev, Vite proxy injects it);
  health probe exempt. SSE: fetch-streaming client or short-lived stream token.
- **Files:** `backend/app/main.py`, new `backend/app/api/security.py`, `apps/web/src/api/{client,events}.ts`, `vite.config.ts`.
- **Dependencies:** none. (Desktop D1 reuses it.)
- **Acceptance:** wrong Host → 403; foreign Origin → 403; no/incorrect token → 401; UI unchanged for the user.
- **Verify:** new API tests for each case; manual: rerun the `Host: evil.example` curl.

### P0-2 One execution gate (SEC-2, ARCH-2) — S, risk low

- **Problem:** `POST /runs`, `/nodes/test`, `/nodes/code/test` bypass the concurrency cap and run budget (8/8 accepted).
- **Implementation:** `ExecutionGate` (cap + budget + cancel registry) used by stored runs and single-node tests; delete
  `POST /runs` (UI doesn't use it); apply a smaller cap to single-node tests.
- **Files:** `services/`, `api/v1/{nodes,workflows,stored}.py`, tests.
- **Acceptance:** N+1 concurrent requests through _any_ endpoint → 429.
- **Verify:** extend `test_concurrent_run_limit` to `/nodes/test`; rerun the 8-parallel probe.

### P0-3 Fix timestamps (BUG-1) — S, risk low

- **Implementation:** a `UTCDateTime` SQLAlchemy `TypeDecorator` that stores UTC and returns tz-aware values (existing
  rows are UTC-naive → interpret as UTC; no data migration needed); frontend formats with `Intl.DateTimeFormat`.
- **Files:** `storage/models.py`, `RunPanel.tsx`.
- **Acceptance:** every API timestamp ends in `Z`; UI time equals system time.
- **Verify:** API test over GET endpoints; screenshot comparison with the system clock.

### P0-4 Never lose edits (DL-1, DL-2) — M, risk medium

- **Implementation:** dirty flag in the store; debounced autosave of the draft (existing `PUT` + `revision`); restore
  the last-opened workflow id on launch; confirm before _New_/_Open_ when dirty; `beforeunload` warning while a save is
  pending; "Saved ✓ / Saving… / Unsaved" indicator.
- **Files:** `state/store.ts` (ideally after splitting out an `editorStore`), `App.tsx`.
- **Acceptance:** edit → reload within 2 s → edits present; _New_ with unsaved changes asks first.
- **Verify:** store unit tests with fake timers; browser script (edit, reload, assert).

### P0-5 Make process lifecycle deterministic in dev (BUG-2, SEC-7) — S, risk low

- **Implementation:** `python -m app` runs without `reload` unless `NODECRAFT_RELOAD=1`; `make dev-api` documents it;
  `make stop` kills by port/pgid.
- **Files:** `backend/app/__main__.py`, `Makefile`.
- **Acceptance:** Ctrl+C or killing the parent leaves nothing listening on the port.
- **Verify:** start, kill, `lsof -i :8000` empty.

### P0-6 Test the HTTPS path (SEC-6) — S, risk none

- **Implementation:** local TLS server fixture (self-signed CA injected into the node's SSL context via a test hook);
  assert success, and failure on an untrusted cert.
- **Acceptance:** automated test covers verify-success and verify-failure.

---

## P1 — Desktop product

See [DESKTOP_APP_PLAN](DESKTOP_APP_PLAN.md) §4 for the full steps. Summary with acceptance:

| ID  | Task                                                                                                     | Effort | Risk                 | Acceptance                                                                                   | Verify                                                   |
| --- | -------------------------------------------------------------------------------------------------------- | ------ | -------------------- | -------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| D0  | Tauri spike (install Rust; window + sidecar + SSE + Monaco in WKWebView; measure size/startup)           | M      | Medium               | Window runs a workflow and streams events; written go/no-go with numbers                     | Manual + recorded measurements in the plan               |
| D1  | Backend runtime config, frozen-safe resources, shutdown endpoint, auth                                   | M      | Medium               | Backend runs from any cwd with config only; P0-1 tests pass                                  | Test suite + `cd / && python -m app.desktop_main`        |
| D2  | Bundle Monaco, configurable base URL/token, fetch-based SSE (ARCH-3)                                     | M      | Medium               | Works offline; zero requests to jsDelivr                                                     | Block network in the browser, run workflow; network log  |
| D3  | Runtime build script (python-build-standalone + deps)                                                    | M      | Medium               | Worker imports `csv`, `sqlite3`, `datetime` with an empty `PATH`                             | Smoke test in the build                                  |
| D4  | Shell lifecycle: port, token, readiness, error screen, graceful shutdown, crash restart, single instance | M      | Medium               | Backend killed → recovers; quit → no leftover processes; start failure → error screen < 25 s | Scripted `pgrep` checks; corrupt the launcher on purpose |
| D5  | App-support data dir + copy-migration from `~/.nodecraft` + pre-migration backups + export               | M      | **High** (user data) | Old DB appears unchanged; failed migration restores backup                                   | Fixture DBs from each schema version (0001–0003)         |
| D6  | Rotating logs + Diagnostics dialog                                                                       | S      | Low                  | Diagnostics shows version/paths/health; canary secret absent from logs                       | Grep test                                                |
| D7  | `.app` + DMG, icon, About/version, ad-hoc signed                                                         | S      | Low                  | Launches from Spotlight; data survives relaunch                                              | Manual checklist                                         |
| D8  | Developer ID signing + notarization                                                                      | M      | Medium               | `spctl -a -vv` accepted                                                                      | Second Mac                                               |
| D9  | Auto-update with backup-before-migrate                                                                   | M      | Medium               | vN→vN+1 keeps data; failed update keeps vN                                                   | Staged release test                                      |

Blocking prerequisites to confirm with you: Apple Developer account (D8/D9), whether Intel Macs matter, app name/icon.

---

## P2 — Core product quality

### P2-1 Debugging that points at the cause — M, risk low

- **Implementation:** auto-select first failed node; map `File "<node>", line N` to a Monaco marker; plain-language
  error summary; _Problems_ tab for validation with click-to-node; _Logs_ tab.
- **Files:** `RunPanel.tsx`, `ResultView.tsx`, `ConfigEditors.tsx`, new `panels/Problems.tsx`.
- **Acceptance:** a `ZeroDivisionError` run selects the node and highlights the line without a click.
- **Verify:** component tests with a fixture run; browser check.

### P2-2 Editor correctness and polish — M, risk medium

- Connection validation (`isValidConnection`: no self-loops/cycles), undo/redo, copy/paste/duplicate, node search,
  command palette (⌘K), shortcuts, responsive toolbar, empty-state, node summary line, minimap toggle.
- **Acceptance:** cannot create a cycle; ⌘Z restores a deleted node; toolbar usable at 800 px.
- **Verify:** React Testing Library + Playwright (below).

### P2-3 Versions you can see — M, risk low

- Version list (note, time, hash), view read-only, diff nodes/config, restore as new draft; run history links to its
  version; rename _Publish_ → _Save version_.
- **Files:** `state/`, new `panels/Versions.tsx`, API already exists.
- **Acceptance:** open v1 of a workflow that has v2; restore creates a new draft, not a rewrite.

### P2-4 Onboarding — M, risk low

- "Debug me" example and first-run empty state per [UI_UX_AUDIT](UI_UX_AUDIT.md) §5.
- **Acceptance:** a new user completes run → failure → fix → resume in under 5 minutes (timed with two testers).

### P2-5 Engineering hygiene — M, risk low

- ESLint + Prettier for the frontend (none today), CI (GitHub Actions: `make check` on macOS and Ubuntu, plus a
  Postgres smoke job), import-linter contracts (ARCH-1), fix layering leaks, split the store (ARCH-5), OpenAPI→TS
  types with a drift check (ARCH-6), `docs/architecture.md` and ADRs (the plan currently lives outside the repo).
- **Acceptance:** CI green on a PR; a deliberate `domain → fastapi` import fails CI; regenerating types yields no diff.

### P2-6 Contracts and data — M, risk medium

- Workflow-format migration framework + clear `unsupported_schema_version` error (ARCH-7), port validation (ARCH-8),
  `type_version`, event pagination + truncation flag (BUG-4), event retention/pruning, typed event union (ARCH-10).
- **Acceptance:** a v0 fixture migrates to v1 byte-stably; a v2 file shows "upgrade Nodecraft"; `/events` pages.

### P2-7 Performance and loop health — S/M, risk low

- Measure event-loop lag under 4 concurrent runs + 10 SSE clients (ARCH-4); move the recorder to a thread pool if
  p99 lag > 50 ms; surface the 200-node run limit in the UI (BUG-3).

### P2-8 Accessibility — M, risk low

- Focus rings, ARIA live regions, keyboard-operable canvas, contrast audit, non-colour status cues.
- **Acceptance:** axe has no serious violations; every action reachable by keyboard.

---

## P3 — Differentiation and future growth (decide after P0–P2)

| Item                                                                  | Why it could matter                             | Prerequisite                           | Effort |
| --------------------------------------------------------------------- | ----------------------------------------------- | -------------------------------------- | ------ |
| Conditional branching (`branch` node, active ports, skip propagation) | Original M3 goal; makes workflows expressive    | Port validation (P2-6)                 | L      |
| Credentials store (Keychain) + redaction (SEC-4)                      | Real APIs need secrets; trust                   | Desktop shell                          | L      |
| Workflow import/export + review-before-run (SEC-5)                    | Sharing, backups, templates                     | Format migrations, `type_version`      | M      |
| Run comparison, breakpoints / step-through, re-run from node          | The product's differentiator: understanding why | P2-1, P2-3                             | L      |
| Subflows / reusable workflows                                         | Reuse, scale                                    | Contracts, export                      | XL     |
| Scheduling / background runs                                          | Automation use cases                            | Desktop lifecycle (runs while closed?) | L      |
| Isolated container worker                                             | Needed before untrusted code                    | See SECURITY_REVIEW §5                 | XL     |
| Hosted mode (Postgres, auth, quotas)                                  | Only if there is demand                         | Isolation                              | XL     |
| Node SDK, packaging, a registry of community nodes                    | Ecosystem                                       | Plugin trust model                     | L      |

Do **not** start: Postgres/Kubernetes/queues, parallel execution, multi-user features, Windows/Linux shells.

---

## Verification plan (Phase 7)

### Current state (measured)

| Layer                    | Exists                                                                      | Gap                                                                                                                     |
| ------------------------ | --------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Backend unit/integration | 120 tests, 92% coverage, pid-based process checks, real HTTP server fixture | HTTPS test; `/nodes/*` limits; Host/Origin/auth; Postgres run                                                           |
| Frontend                 | 18 tests: mapper, store, JsonField, panels                                  | No canvas interaction tests (connect/delete/undo), no component tests for Inspector/RunPanel flows, coverage unmeasured |
| End-to-end               | None automated (manual browser checks only)                                 | Playwright suite                                                                                                        |
| Persistence              | Restart test, migration-drift test                                          | Old-schema fixture DBs; backup/restore                                                                                  |
| Performance              | Ad-hoc measurements only                                                    | Repeatable benchmark with thresholds                                                                                    |
| Desktop                  | None                                                                        | Everything below                                                                                                        |

### Test suites to add

1. **E2E (Playwright against the real backend, temp data dir):** create nodes → connect → run → inspect → fail →
   fix → resume; autosave + reload; cancel mid-run; backend killed mid-run; two-tab conflict.
2. **Graph validation:** cycles, self-loops, dangling edges, bad ports, >200 nodes, duplicate ids (backend tests exist
   for most; add ports and UI-level prevention).
3. **Persistence:** fixture DBs for schema 0001, 0002, 0003 upgrade to head with data intact; failing migration restores backup.
4. **Reliability:** timeout, cancel, retry, resume (exist) + grandchild process cleanup + server SIGKILL.
5. **Security:** per [SECURITY_REVIEW](SECURITY_REVIEW.md) §6.
6. **Performance (thresholds as acceptance, measured on this Mac):** 40-node chain < 2 s (now 0.9 s); 200-node run
   < 10 s; 300-node workflow open < 500 ms and selection < 100 ms (now ~190/30 ms in dev); desktop cold start < 3 s.
7. **Desktop:** the checklist in [DESKTOP_APP_PLAN](DESKTOP_APP_PLAN.md) §5 as a scripted smoke test run on every
   release build.

### Measurable acceptance criteria (examples adapted to the real implementation)

- A saved workflow is present after quitting and reopening the packaged app.
- A failed node shows its error, traceback line, input and logs; selecting the run restores them.
- A run executes exactly the version recorded on the run (exists: `test_run_is_pinned_persisted_and_listed`).
- A packaged app starts with no dev server and no network (D2/D3).
- After quit no backend or worker processes remain (D4).
- A backend start failure shows an error screen with log tail within 25 s (D4).
- Every timestamp shown matches the system clock (P0-3).
- Foreign Host/Origin or missing token never reaches execution (P0-1).

### Known gaps in current tests (be aware)

Frontend tests never mount the full `App`; the file-size-limit test asserts only that the node failed; the macOS
memory-limit test is skipped; concurrency tests rely on short sleeps; `worker_entry.py` is covered only indirectly.

## Status after the full implementation pass (2026-10-20)

Done: P0 items; branching; credentials; import/export; version UI and format migrations; undo/redo, palette, themes,
first-run tutorial; desktop D0–D7; ESLint/Prettier/import-linter; OpenAPI-generated types; CI workflow
(`.github/workflows/ci.yml`, **written but never run on GitHub**); ADRs and `docs/architecture.md`.
Still open: D8/D9, Playwright e2e, Windows/Linux, sandboxed execution, Postgres, scheduling, parallel execution.
