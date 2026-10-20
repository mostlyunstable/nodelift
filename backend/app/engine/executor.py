"""Sequential workflow executor. Independent of FastAPI, DB and React Flow."""

import asyncio
import json
import time
import uuid
from typing import Any

from app.domain.nodes import NodeContext, NodeRegistry
from app.domain.run import ExecutionRun, NodeExecution, NodeStatus, RunObserver, RunStatus
from app.domain.secrets import Redactor, SecretResolver, SecretStore
from app.domain.workflow import WorkflowDefinition, WorkflowEdge, retry_policy, topological_order

# Deterministic failures are never retried: running the same code again cannot change them.
RETRIABLE_ERRORS = {"runtime_error", "timeout", "worker_crashed", "network_error", "http_error"}


def _port_active(fired: list[str] | None, port: str) -> bool:
    return fired is None or port in fired


def _node_input(
    incoming: list[WorkflowEdge],
    active: list[WorkflowEdge],
    outputs: dict[str, Any],
    run_input: Any,
) -> Any:
    """What a node receives. The SHAPE depends only on the graph (one incoming edge: the value;
    several: an object keyed by upstream node id), so it does not change with which branch ran.
    Only edges that actually fired contribute."""
    if not incoming:
        return run_input
    if len(incoming) == 1:
        return outputs[active[0].source.node]
    return {e.source.node: outputs[e.source.node] for e in active}


def _same_json(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


async def _sleep_or_cancel(seconds: float, cancel: asyncio.Event | None) -> None:
    if cancel is None:
        await asyncio.sleep(seconds)
        return
    try:
        await asyncio.wait_for(cancel.wait(), seconds)
    except TimeoutError:
        pass


async def execute_workflow(
    wf: WorkflowDefinition,
    registry: NodeRegistry,
    run_input: Any = None,
    timeout_s: float = 30,
    node_inputs: dict[str, Any] | None = None,
    observer: RunObserver | None = None,
    run_id: str | None = None,
    cancel: asyncio.Event | None = None,
    max_run_s: float | None = None,
    completed: dict[str, NodeExecution] | None = None,
    secrets: SecretStore | None = None,
) -> ExecutionRun:
    """Run nodes in dependency order. Fail-fast: downstream of a failed/skipped node is skipped.

    - `cancel`: when set, the running node is killed and the remaining nodes are skipped.
    - `max_run_s`: wall-clock budget for the whole run.
    - `completed`: earlier results; a node is reused only if it succeeded and gets the same input.
    - `secrets`: where {{credential:NAME}} references are resolved; values are masked in results.
    - `node_inputs` overrides the computed input for entry nodes.
    """
    order = topological_order(wf)
    if order is None:
        raise ValueError("workflow has a cycle")
    nodes = {n.id: n for n in wf.nodes}
    outputs: dict[str, Any] = {}
    fired: dict[str, list[str] | None] = {}  # succeeded node -> output ports that fired
    dead: set[str] = set()  # failed, cancelled, or skipped because of one of those
    records: list[NodeExecution] = []
    final: dict[str, NodeStatus] = {}
    reason: str | None = None
    start = time.monotonic()
    redactor = Redactor()  # every secret value used in this run, masked wherever it could leak
    resolver = SecretResolver(secrets, redactor) if secrets is not None else None

    async def emit_finished(rec: NodeExecution, will_retry: bool = False) -> None:
        records.append(rec)
        if observer:
            await observer.node_finished(rec, will_retry)

    async def skip(nid: str, why: str) -> None:
        final[nid] = "skipped"
        await emit_finished(NodeExecution(node_id=nid, status="skipped", skip_reason=why))

    for nid in order:
        incoming = [e for e in wf.edges if e.target.node == nid]
        if reason is None and cancel is not None and cancel.is_set():
            reason = "cancelled"
        if reason is None and max_run_s is not None and time.monotonic() - start >= max_run_s:
            reason = "run_timeout"
        if reason is not None or any(e.source.node in dead for e in incoming):
            dead.add(nid)  # fail-fast: whatever depends on a failure does not run
            await skip(nid, "run_stopped" if reason is not None else "upstream_failed")
            continue
        active = [
            e
            for e in incoming
            if e.source.node in outputs and _port_active(fired.get(e.source.node), e.source.port)
        ]
        if incoming and not active:
            await skip(nid, "branch_not_taken")  # every way in was a branch that did not fire
            continue

        inp = _node_input(incoming, active, outputs, run_input)
        if node_inputs and nid in node_inputs and not incoming:
            inp = node_inputs[nid]
        previous = completed.get(nid) if completed else None
        if previous and previous.status == "succeeded" and _same_json(previous.input, inp):
            # Same code (the caller only offers nodes whose settings are unchanged) and same input:
            # the earlier result is still valid, so don't run it again.
            reused = previous.model_copy(
                update={"reused": True, "attempt": 1, "duration_ms": 0, "logs": []}
            )
            outputs[nid] = reused.output
            fired[nid] = reused.activated_ports
            final[nid] = "succeeded"
            await emit_finished(reused)
            continue
        max_attempts, backoff_ms = retry_policy(nodes[nid])
        for attempt in range(1, max_attempts + 1):
            remaining = None if max_run_s is None else max_run_s - (time.monotonic() - start)
            node_timeout = timeout_s if remaining is None else max(0.1, min(timeout_s, remaining))
            if observer:
                await observer.node_started(nid, attempt)
            impl = registry.get(nodes[nid].type)
            assert impl is not None  # guaranteed by validate_workflow before execution
            res = await impl.execute(
                NodeContext(node_timeout, cancel, resolver), inp, nodes[nid].config
            )
            res = redactor.result(res)  # nothing secret is stored, streamed or shown
            cancelled = res.error is not None and res.error.type == "cancelled"
            status: NodeStatus = "cancelled" if cancelled else res.status
            budget_left = max_run_s is None or time.monotonic() - start < max_run_s
            will_retry = (
                status == "failed"
                and attempt < max_attempts
                and res.error is not None
                and res.error.type in RETRIABLE_ERRORS
                and not (cancel is not None and cancel.is_set())
                and budget_left
            )
            rec = NodeExecution(
                node_id=nid, status=status, input=inp, output=res.output, logs=res.logs,
                error=res.error, duration_ms=res.duration_ms, attempt=attempt,
                activated_ports=res.activated_ports if status == "succeeded" else None,
            )  # fmt: skip
            await emit_finished(rec, will_retry)
            final[nid] = status
            if not will_retry:
                break
            await _sleep_or_cancel(backoff_ms / 1000, cancel)

        if final[nid] == "succeeded":
            outputs[nid] = records[-1].output
            fired[nid] = records[-1].activated_ports
        else:
            dead.add(nid)
            if final[nid] == "cancelled":
                reason = "cancelled"

    statuses = set(final.values())
    run_status: RunStatus
    if reason == "cancelled" or "cancelled" in statuses:
        run_status, reason = "cancelled", "cancelled"
    elif "failed" in statuses or reason == "run_timeout":
        run_status = "failed"
    else:
        run_status = "succeeded"
    return ExecutionRun(
        id=run_id or f"run_{uuid.uuid4().hex[:12]}",
        status=run_status,
        nodes=records,
        duration_ms=int((time.monotonic() - start) * 1000),
        reason=reason,
    )
