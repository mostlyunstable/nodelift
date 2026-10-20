# 0003 — Immutable versions; runs pinned; resume reuses only what is still valid

**Status:** accepted (resume semantics revised after the first-run tutorial exposed a flaw)

**Decision.** Editing changes a mutable draft (optimistic `revision`, autosaved). Running snapshots the draft into an
immutable version (deduplicated by a hash that ignores layout) and the run records that version. **Resume** starts a new
run on the _current_ draft and reuses a node's earlier result only if it succeeded, its type and settings are
unchanged, and it receives exactly the input it had. Reused nodes are never executed.

**Why.** The first version resumed the _same_ version, so fixing the bug and pressing Resume re-ran the broken code.
Input equality makes reuse safe: a change upstream re-runs what depends on it.

**Consequences.** Non-idempotent side effects of a node that was in flight when a run died may repeat. Retries require an
explicit `idempotent: true` opt-in.
