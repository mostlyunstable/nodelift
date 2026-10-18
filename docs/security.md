# Security model (MVP)

**Code nodes run unsandboxed on your machine.** Running user Python in a subprocess is *not* a security boundary.
Treat every workflow like a script you are running yourself.

## Safeguards in the MVP
- API binds to `127.0.0.1` only; other hosts are refused unless `NODECRAFT_ALLOW_UNSAFE_REMOTE=1`.
- Worker: isolated interpreter (`-I`), scrubbed environment (no inherited secrets), temp cwd, own process group
  (killed on timeout), CPU/core rlimits, capped result (5 MB) and log sizes.

## NOT provided (prerequisites before hosting or running untrusted code)
Container/microVM isolation, read-only filesystem, seccomp, non-root user, cgroup memory/pids limits,
network deny-by-default, authentication, per-user quotas, secret injection and log redaction.
Never expose `/api/v1/nodes/code/test` or workflow runs to the public internet.
