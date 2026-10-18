"""Workflow definition (schema_version 1) and semantic validation. Layout lives in `ui`."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SUPPORTED_NODE_TYPES = {"code.python"}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkflowNode(Strict):
    id: str = Field(min_length=1)
    type: str
    name: str = ""
    config: dict[str, Any] = {}


class Endpoint(Strict):
    node: str
    port: str = "out"


class WorkflowEdge(Strict):
    id: str = ""
    source: Endpoint
    target: Endpoint


class WorkflowDefinition(Strict):
    schema_version: Literal[1] = 1
    id: str = ""
    name: str = "Untitled"
    nodes: list[WorkflowNode] = []
    edges: list[WorkflowEdge] = []
    ui: dict[str, Any] = {}  # layout only; ignored by the engine


class ValidationIssue(BaseModel):
    code: str
    message: str
    node_id: str | None = None


def topological_order(wf: WorkflowDefinition) -> list[str] | None:
    """Kahn's algorithm in definition order for stability. None if the graph has a cycle."""
    indeg = {n.id: 0 for n in wf.nodes}
    out: dict[str, list[str]] = {n.id: [] for n in wf.nodes}
    for e in wf.edges:
        if e.source.node in out and e.target.node in indeg:
            out[e.source.node].append(e.target.node)
            indeg[e.target.node] += 1
    ready = [n.id for n in wf.nodes if indeg[n.id] == 0]
    order: list[str] = []
    while ready:
        cur = ready.pop(0)
        order.append(cur)
        for nxt in out[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                ready.append(nxt)
    return order if len(order) == len(wf.nodes) else None


def validate_workflow(wf: WorkflowDefinition) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    ids = [n.id for n in wf.nodes]
    for dup in {i for i in ids if ids.count(i) > 1}:
        issues.append(
            ValidationIssue(code="duplicate_node_id", message=f"Duplicate id {dup}", node_id=dup)
        )
    known = set(ids)
    for n in wf.nodes:
        if n.type not in SUPPORTED_NODE_TYPES:
            issues.append(
                ValidationIssue(
                    code="unknown_node_type", message=f"Unknown type {n.type}", node_id=n.id
                )
            )
        elif n.type == "code.python" and not isinstance(n.config.get("source"), str):
            issues.append(
                ValidationIssue(
                    code="invalid_config", message="config.source must be a string", node_id=n.id
                )
            )
    for e in wf.edges:
        for end in (e.source, e.target):
            if end.node not in known:
                issues.append(
                    ValidationIssue(
                        code="dangling_edge", message=f"Edge references missing node {end.node}"
                    )
                )
        if e.source.node == e.target.node:
            issues.append(
                ValidationIssue(
                    code="self_loop", message="Node connected to itself", node_id=e.source.node
                )
            )
    if (
        not any(i.code in {"duplicate_node_id", "dangling_edge"} for i in issues)
        and topological_order(wf) is None
    ):
        issues.append(ValidationIssue(code="cycle", message="Workflow contains a cycle"))
    return issues
