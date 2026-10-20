"""Workflow definition (schema_version 1) and semantic validation. Layout lives in `ui`."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.migrations import CURRENT_SCHEMA_VERSION, unsupported_message
from app.domain.nodes import NodeRegistry

MAX_NODES = 200
MAX_ATTEMPTS = 5
MAX_BACKOFF_MS = 60_000


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
    schema_version: int = CURRENT_SCHEMA_VERSION
    id: str = ""
    name: str = "Untitled"
    nodes: list[WorkflowNode] = []
    edges: list[WorkflowEdge] = []
    ui: dict[str, Any] = {}  # layout only; ignored by the engine

    @field_validator("schema_version")
    @classmethod
    def _known_version(cls, v: int) -> int:
        if v != CURRENT_SCHEMA_VERSION:
            raise ValueError(unsupported_message(v, CURRENT_SCHEMA_VERSION))
        return v


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


def retry_policy(node: WorkflowNode) -> tuple[int, int]:
    """(max_attempts, backoff_ms). Retries only apply to nodes explicitly marked idempotent."""
    retry = node.config.get("retry")
    if node.config.get("idempotent") is not True or not isinstance(retry, dict):
        return 1, 0
    attempts = retry.get("max_attempts", 1)
    backoff = retry.get("backoff_ms", 0)
    if not isinstance(attempts, int) or not isinstance(backoff, int):
        return 1, 0
    return max(1, min(attempts, MAX_ATTEMPTS)), max(0, min(backoff, MAX_BACKOFF_MS))


def _retry_issues(n: WorkflowNode) -> list[ValidationIssue]:
    out: list[ValidationIssue] = []
    if "idempotent" in n.config and not isinstance(n.config["idempotent"], bool):
        out.append(
            ValidationIssue(
                code="invalid_config", message="config.idempotent must be a boolean", node_id=n.id
            )
        )
    retry = n.config.get("retry")
    if retry is None:
        return out
    ok = (
        isinstance(retry, dict)
        and isinstance(retry.get("max_attempts", 1), int)
        and 1 <= retry.get("max_attempts", 1) <= MAX_ATTEMPTS
        and isinstance(retry.get("backoff_ms", 0), int)
        and 0 <= retry.get("backoff_ms", 0) <= MAX_BACKOFF_MS
    )
    if not ok:
        out.append(
            ValidationIssue(
                code="invalid_config",
                message=(
                    f"config.retry needs max_attempts 1-{MAX_ATTEMPTS}"
                    f" and backoff_ms 0-{MAX_BACKOFF_MS}"
                ),
                node_id=n.id,
            )
        )
    elif retry.get("max_attempts", 1) > 1 and n.config.get("idempotent") is not True:
        out.append(
            ValidationIssue(
                code="retry_requires_idempotent",
                message="Retries re-run code, so the node must be marked idempotent",
                node_id=n.id,
            )
        )
    return out


def validate_workflow(wf: WorkflowDefinition, registry: NodeRegistry) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    ids = [n.id for n in wf.nodes]
    if len(ids) > MAX_NODES:
        issues.append(ValidationIssue(code="too_many_nodes", message=f"At most {MAX_NODES} nodes"))
    for dup in {i for i in ids if ids.count(i) > 1}:
        issues.append(
            ValidationIssue(code="duplicate_node_id", message=f"Duplicate id {dup}", node_id=dup)
        )
    known = set(ids)
    by_id = {n.id: n for n in wf.nodes}
    for n in wf.nodes:
        impl = registry.get(n.type)
        if impl is None:
            issues.append(
                ValidationIssue(
                    code="unknown_node_type", message=f"Unknown type {n.type}", node_id=n.id
                )
            )
            continue
        for problem in impl.validate_config(n.config):
            issues.append(ValidationIssue(code="invalid_config", message=problem, node_id=n.id))
        issues.extend(_retry_issues(n))
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
        for end, ports_of in ((e.source, "outputs"), (e.target, "inputs")):
            node = by_id.get(end.node)
            impl = registry.get(node.type) if node else None
            if node is None or impl is None:
                continue  # already reported as dangling / unknown type
            valid = {p.name for p in getattr(impl.definition, ports_of)}
            if end.port not in valid:
                kind = "output" if ports_of == "outputs" else "input"
                issues.append(
                    ValidationIssue(
                        code="unknown_port",
                        message=(
                            f"{node.type} has no {kind} port {end.port!r} (has {sorted(valid)})"
                        ),
                        node_id=node.id,
                    )
                )
    if (
        not any(i.code in {"duplicate_node_id", "dangling_edge"} for i in issues)
        and topological_order(wf) is None
    ):
        issues.append(ValidationIssue(code="cycle", message="Workflow contains a cycle"))
    return issues
