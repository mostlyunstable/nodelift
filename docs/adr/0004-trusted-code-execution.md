# 0004 — User code runs in a child process in trusted mode; it is not a sandbox

**Status:** accepted for local use; **must change before hosting or running untrusted code**

**Decision.** Python nodes run in a separate process (scrubbed environment, temp directory, CPU/file-size/open-file
limits, memory limit on Linux only, own process group killed on timeout/cancel, self-exit if the server dies). This is
documented everywhere as _not_ isolation: the code runs with the user's permissions.

**Why.** A developer tool runs the developer's own scripts. Pretending a subprocess is a sandbox would be worse than
saying so. Imported workflows are therefore previewed and never run automatically.

**Before untrusted code:** per-run container or microVM, no host mounts, network deny-by-default, cgroup limits,
authentication and quotas (see `docs/audit/SECURITY_REVIEW.md` §5).
