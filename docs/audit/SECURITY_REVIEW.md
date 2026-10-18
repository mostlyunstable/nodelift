# Security review

Audit date 2026-10-18, `main@4ec6651`. Existing baseline: [../security.md](../security.md). Probes were run against a
throwaway server with a temporary data directory; nothing touched real user data.

## 1. Trust model

| Mode | Who is trusted | Status |
|---|---|---|
| **A. Trusted local developer** (today's target) | The person at the keyboard; workflows are their own scripts | Supported. User code is **not** sandboxed and can do anything the user can |
| **B. Desktop app** | Same person, but a web page they browse or a downloaded workflow file is hostile | **Needs P0 work** (API auth, Host/Origin checks, safe import) |
| **C. Hosted / multi-user / untrusted code** | Nobody | **Not supported.** Requires a different execution architecture (below) |

A subprocess with a timeout is not a sandbox. Nothing in the repository claims otherwise (`docs/security.md`, README,
the UI warning banner), which is correct.

## 2. What runs where (evidence)

- User Python runs in a **child process**, never in the FastAPI process (`runtime/subprocess_runner.py`: `-I`,
  scrubbed env, temp cwd, own process group killed on timeout/cancel). Tests assert the real worker pid dies on timeout
  and on cancel, and that a worker exits when its parent is SIGKILLed.
- Limits: CPU and file-size and open-file rlimits, 5 MB result cap, 64 KB log cap, run wall-clock budget, 4 concurrent
  runs (stored runs only). **Memory limit is Linux-only**; macOS does not enforce `RLIMIT_AS`.
- The HTTP node runs **in the server process** behind an address guard (`runtime/net_guard.py`).

## 3. Findings

### SEC-1 — Unauthenticated, Host-agnostic code-execution API (S2) — **FIXED in P0-1**
- Measured: `curl -H 'Host: evil.example' /api/v1/health` → 200. No token required anywhere.
- Measured: a cross-site *simple* POST (`text/plain`) is rejected by FastAPI with 422, and a JSON preflight returns
  405 with no CORS headers. So a browser cannot POST JSON cross-origin today. That protection is incidental.
- **DNS rebinding** removes the same-origin barrier: a page on `attacker.example` whose DNS flips to `127.0.0.1` becomes
  "same-origin" with the API, and can then POST code to `/nodes/code/test`. The precondition (no Host validation, no
  token) is verified; I did **not** build an end-to-end exploit.
- Fix (P0, S): `TrustedHostMiddleware` allowing only `127.0.0.1`/`localhost` (+ the chosen port); reject requests
  whose `Origin` is present and not on an allowlist; require `Authorization: Bearer <per-launch token>` on every
  route except a minimal health probe. SSE needs a header-capable client (`fetch` streaming) or a short-lived stream
  token because `EventSource` cannot set headers.
- Acceptance: requests with a wrong Host, a foreign Origin, or no token get 403/401; the UI still works; a test
  covers each.

### SEC-2 — Limits bypass (S3) — **FIXED in P0-2**
`POST /runs` (legacy ad-hoc) and `POST /nodes/test` / `/nodes/code/test` ignore the concurrency cap and run budget
(8 of 8 parallel 2-second runs accepted; stored runs gave 202×4 then 429×2). Anyone (or any bug) can fork-bomb the
machine with workers. Fix: one `ExecutionGate` used by every path; delete `POST /runs`. Effort S.

### SEC-3 — Trusted-mode code has full user privileges (accepted locally, S2 if shared)
Measured: a code node read `SQLite format 3` from the app database. No restriction is applied to other files, sockets or
the Nodecraft API itself (inferred from the design; only the database read was tested). The scrubbed environment prevents *accidental* leakage only. Do not describe this as
isolation anywhere in the product.

### SEC-4 — Secrets and sensitive data at rest (S3)
No credential store exists. `http.request` headers/bodies live in the workflow JSON; node inputs/outputs, HTTP response
bodies and logs are stored unredacted in `node_executions`. There is no redaction pass, retention policy, or export
filter. Before credentials ship: `CredentialReference` rows with the secret in the macOS Keychain, injection at
execution time only for nodes that declare the need, redaction of known secret values in logs/events/outputs,
and an export that omits secrets. Until then the UI already tells users not to put secrets in headers.

### SEC-5 — Imported/third-party code (S4 now)
There is no workflow import yet. When added, treat imported workflows as untrusted *code*: show a review/preview
(node types, code, URLs), never auto-run, and never load plugins from a workflow. Plugins
(`NODECRAFT_NODE_PLUGINS`) run in-process with full privileges and are operator configuration only.

### SEC-6 — HTTP node (S3 residual)
Strengths (unit-tested): public addresses only (IPv4/IPv6 incl. mapped, 6to4, NAT64, Teredo), every DNS answer checked,
connection pinned to the checked address, no redirects, size/time caps, query strings never logged. HTTPS with
certificate verification works (measured against example.com; an expired certificate was rejected) but has no
automated test. Residual: runs in the server process (a parser bug there is server-side), no egress allowlist.

### SEC-7 — Process hygiene (S3 for desktop)
`uvicorn reload=True` leaves a reloader child that kept port 8000 after the parent was killed (observed twice). A
desktop shell must own process groups and shut the backend down deterministically.

## 4. Recommended local development mode now
Keep the current model, plus: SEC-1 and SEC-2 fixes; the banner stays; warn on import; show a "Trusted mode: code runs
as you" note on first run; make the worker environment an explicit allowlist (already scrubbed) and document that
file/network access is open. Optional cheap hardening on macOS: run workers under `sandbox-exec` with a deny-network
and restricted-write profile (deprecated but functional; test before relying on it, and don't call it a sandbox).

## 5. Architecture required before untrusted code or remote users
1. Per-run isolated worker: container or microVM (gVisor/Firecracker/Docker), read-only root, no host mounts, non-root
   user, seccomp, cgroup CPU/memory/pids limits, tmpfs scratch.
2. Network deny-by-default with an egress proxy/allowlist; move the HTTP node into the worker tier.
3. Separate control plane from execution plane; workers get only the single run's input and a scoped, expiring credential.
4. AuthN/AuthZ with per-tenant isolation of workflows, runs, secrets; quotas and rate limits; audit log.
5. Secrets in a managed secret store; log/event redaction enforced centrally.
6. Postgres, backups, and encrypted storage.
None of this is started, and none should start before the desktop product is solid.

## 6. Security test plan
| Test | Acceptance |
|---|---|
| Wrong `Host` header → 403 | automated API test |
| Foreign `Origin` → 403; missing/incorrect token → 401 | automated |
| N+1 concurrent executions through *any* endpoint → 429 | automated, covers `/nodes/test` |
| Worker process and its children are dead after timeout, cancel, server SIGKILL | exists (pid-based); extend to grandchildren |
| HTTP node: private/metadata/mapped IPs, redirects, rebinding | exists (unit); add HTTPS-against-local-TLS-server test |
| Secrets never appear in events, logs, exports | add once credentials exist; seed a canary secret and grep the DB and exports |
| Imported workflow with `http.request` to `127.0.0.1` | blocked unless dev flag; import UI shows the URL |
