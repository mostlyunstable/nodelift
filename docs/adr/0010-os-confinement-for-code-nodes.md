# 0010 — OS confinement for code nodes (supersedes the "no sandbox" part of ADR 0004)

**Status:** accepted

**Decision.** On macOS, code nodes run under Seatbelt (`sandbox-exec`) with a generated profile: no network unless the node opts in
(`allow_network`), writes only inside the worker's temp folder, no reads of the user's home folder except the interpreter and the temp
folder. Children inherit the profile. A memory watchdog (macOS ignores `RLIMIT_AS`) kills a worker group above the limit
(`memory_limit` error). `NODECRAFT_SANDBOX=auto|off|required`; `required` refuses to run code if confinement is unavailable.
The behaviour is tested from inside the sandbox: user code tries to read a secret under `$HOME`, write to `$HOME` and `/tmp`,
connect to a local server and resolve DNS; the kernel denies each, and the same probe succeeds with the sandbox off.

**What this is not.** Not a VM or container. Reads outside the home folder (system files, `/tmp`) and file existence checks still work;
CPU and memory use are limited only by rlimits and the watchdog; `sandbox-exec` is deprecated by Apple (still enforced today, but may
go away). Linux and Windows have no equivalent yet: there the node runs with the user's full permissions, and `/system/info` says so
(`sandbox.active: false`). Hosting multiple users still requires containers or microVMs (ADR 0004).
