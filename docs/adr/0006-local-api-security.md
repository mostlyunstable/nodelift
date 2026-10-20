# 0006 — Local API: Host/Origin checks, per-launch token, CORS allowlist

**Status:** accepted

**Context.** The API executes code. A web page the user visits must not be able to reach it (DNS rebinding).

**Decision.** Every request must carry a loopback `Host`; any `Origin` must be on an allowlist; when `NODECRAFT_API_TOKEN`
is set (always, in the desktop app) a bearer token is required on every route except `/health`. CORS is allowed only for
the configured origins (the desktop webview, the dev server) and is the outermost middleware so credential-less
preflights are answered. One `ExecutionGate` caps concurrent runs and single-node tests for every execution path.

**Consequences.** A non-loopback bind is refused unless a token is also set. SSE uses `fetch` so it can carry the token.
