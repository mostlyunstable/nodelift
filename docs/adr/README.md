# Architecture decision records

One short file per significant decision: what we chose, why, what we rejected, and what would make us revisit it.
Newest decisions go at the end. Do not rewrite history: supersede an old ADR with a new one.

| #                                             | Decision                                                                     |
| --------------------------------------------- | ---------------------------------------------------------------------------- |
| [0001](0001-sse-for-live-runs.md)             | Live run updates over Server-Sent Events, read with `fetch`                  |
| [0002](0002-sqlite-repositories-backups.md)   | SQLite behind repository protocols; backups before migrations                |
| [0003](0003-versions-and-resume.md)           | Immutable versions; runs pinned; resume reuses only what is still valid      |
| [0004](0004-trusted-code-execution.md)        | User code runs in a child process in trusted mode; it is not a sandbox       |
| [0005](0005-desktop-shell-and-runtime.md)     | Tauri shell with a bundled Python runtime, not a frozen executable           |
| [0006](0006-local-api-security.md)            | Local API: Host/Origin checks, per-launch token, CORS allowlist              |
| [0007](0007-branching-semantics.md)           | Branching by output ports; what runs, what is skipped, what a merge receives |
| [0008](0008-secrets.md)                       | Credentials in the system keychain, referenced by name, masked everywhere    |
| [0009](0009-static-dependency-analysis.md)    | Static dependency analysis with explicit confidence                          |
| [0010](0010-os-confinement-for-code-nodes.md) | OS confinement for code nodes (macOS Seatbelt, memory watchdog)              |
| [0011](0011-approved-commands-and-patches.md) | Approved commands and reviewable patches for imported repositories           |
| [0012](0012-explorer-graph-as-nested-cards.md) | The Explorer draws folders as nested cards, and draws lines only when asked |
