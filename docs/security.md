# Security model (MVP)

**Code nodes run unsandboxed on your machine.** Running user Python in a subprocess is *not* a security boundary.
Treat every workflow like a script you are running yourself.

## Safeguards in the MVP
- API binds to `127.0.0.1` only; other hosts are refused unless `NODECRAFT_ALLOW_UNSAFE_REMOTE=1`.
- Worker: isolated interpreter (`-I`), scrubbed environment (no inherited secrets), temp cwd, own process group
  (killed on timeout), CPU/core rlimits, capped result (5 MB) and log sizes.

## Reliability controls (M6)
- Runs can be cancelled; the worker's process group is killed. Workers also exit if the server dies (parent watchdog).
- Limits: per-node timeout, run wall-clock budget, concurrent-run cap, max 200 nodes per workflow, 5 MB result cap,
  CPU/file-size/open-file rlimits, memory rlimit on Linux only. These stop accidents, not a malicious author:
  user code can still read files and use the network.
- Retries and resume can run code again after an interruption. A node that was in flight when the server died has no
  stored result, so resuming re-runs it; mark nodes idempotent only if repeating them is safe.

## Outbound HTTP (`http.request` node)
Runs inside the server process, not the worker. The SSRF guard (`runtime/net_guard.py`) allows public addresses only,
connects to the address it validated, and never follows redirects. This is defence in depth, not a substitute for
network-level egress policy in a hosted deployment. Node plugins (`NODECRAFT_NODE_PLUGINS`) run with full server
privileges and must be trusted.

## NOT provided (prerequisites before hosting or running untrusted code)
Container/microVM isolation, read-only filesystem, seccomp, non-root user, cgroup memory/pids limits,
network deny-by-default, authentication, per-user quotas, secret injection and log redaction.
Never expose `/api/v1/nodes/code/test` or workflow runs to the public internet.
