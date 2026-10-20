# 0007 — Branching by output ports

**Status:** accepted

**Decision.** A node result may name the output ports that fired (`activated_ports`; none named = all). `logic.branch`
evaluates a condition on a path into its input and fires `true` or `false`, passing the input through unchanged.
For a node with incoming edges:

1. If the run was stopped, or any source **failed/was cancelled/was skipped because of a failure** → skipped
   (`upstream_failed` / `run_stopped`): fail-fast is unchanged.
2. Else if no incoming edge fired (all sources are untaken branches or skipped) → skipped (`branch_not_taken`). This is
   not a failure and does not fail the run.
3. Else it runs. **Input shape depends only on the graph:** one incoming edge → the value itself; several → an object keyed
   by source node id containing only the edges that fired. A merge therefore sees whichever side ran.

Edge ports are validated against node definitions. A reused (resumed) branch restores its `activated_ports`.
