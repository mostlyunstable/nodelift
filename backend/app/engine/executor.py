"""Sequential workflow executor. Independent of FastAPI, DB and React Flow."""

import time
import uuid
from typing import Any

from app.domain.ports import CodeRunner
from app.domain.run import ExecutionRun, NodeExecution, RunObserver
from app.domain.workflow import WorkflowDefinition, topological_order


def _node_input(
    wf: WorkflowDefinition, node_id: str, outputs: dict[str, Any], run_input: Any
) -> Any:
    sources = [e.source.node for e in wf.edges if e.target.node == node_id]
    if not sources:
        return run_input
    if len(sources) == 1:
        return outputs[sources[0]]
    return {s: outputs[s] for s in sources}  # fan-in: keyed by upstream node id


async def execute_workflow(
    wf: WorkflowDefinition,
    runner: CodeRunner,
    run_input: Any = None,
    timeout_s: float = 30,
    node_inputs: dict[str, Any] | None = None,
    observer: RunObserver | None = None,
    run_id: str | None = None,
) -> ExecutionRun:
    """Run nodes in dependency order. Fail-fast: downstream of a failed/skipped node is skipped.

    `node_inputs` overrides the computed input for entry nodes (used for per-node test input).
    """
    order = topological_order(wf)
    if order is None:
        raise ValueError("workflow has a cycle")
    nodes = {n.id: n for n in wf.nodes}
    outputs: dict[str, Any] = {}
    blocked: set[str] = set()
    records: list[NodeExecution] = []
    start = time.monotonic()
    for nid in order:
        upstream = [e.source.node for e in wf.edges if e.target.node == nid]
        if any(u in blocked for u in upstream):
            blocked.add(nid)
            skipped = NodeExecution(node_id=nid, status="skipped")
            records.append(skipped)
            if observer:
                await observer.node_finished(skipped)
            continue
        inp = _node_input(wf, nid, outputs, run_input)
        if node_inputs and nid in node_inputs and not upstream:
            inp = node_inputs[nid]
        if observer:
            await observer.node_started(nid)
        res = await runner.run(nodes[nid].config["source"], inp, timeout_s)
        record = NodeExecution(
            node_id=nid,
            status=res.status,
            input=inp,
            output=res.output,
            logs=res.logs,
            error=res.error,
            duration_ms=res.duration_ms,
        )
        records.append(record)
        if observer:
            await observer.node_finished(record)
        if res.status == "succeeded":
            outputs[nid] = res.output
        else:
            blocked.add(nid)
    failed = any(r.status == "failed" for r in records)
    return ExecutionRun(
        id=run_id or f"run_{uuid.uuid4().hex[:12]}",
        status="failed" if failed else "succeeded",
        nodes=records,
        duration_ms=int((time.monotonic() - start) * 1000),
    )
