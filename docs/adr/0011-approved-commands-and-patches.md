# 0011 — Approved commands and reviewable patches for imported repositories

**Status:** accepted (R6)

**Decision.** Importing and analysing never run repository code. Running anything needs three explicit steps by the user: prepare a
workspace (a full unpacked copy of the pinned commit under the app's data folder), review the exact command and its confinement in an
approval dialog, and approve. The API refuses a command unless `approved_command` equals `command`. Commands are split with `shlex` and
executed without a shell; executables must be found on a sanitised PATH or be a file inside the workspace.
On macOS each command runs under Seatbelt (ADR 0010): no network and no home-folder reads unless the user ticks those boxes, writes only
inside the workspace and a scratch folder, no inherited environment or secrets, `HOME` and `TMPDIR` point at the scratch folder. Nodecraft never
installs packages; an install fails without network. Where confinement is unavailable the user must tick an extra acknowledgement.
Output is capped at 256 KB, the time limit is 300 s (max 900), memory is watched, cancel and timeout kill the process group.
Proposed fixes are stored as full replacement text for one file and shown as a unified diff; they live apart from the imported files, are
applied to the workspace copy only on request (refused if that file changed meanwhile), can be reverted, and exported as a `git apply`-able `.patch`.
**Limits.** No AI suggestions (no provider is configured); one command at a time; command history is in memory only; Linux and Windows run
unconfined with acknowledgement; the user's own Python must already have the test framework installed.
