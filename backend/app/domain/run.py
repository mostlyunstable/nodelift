from typing import Any, Literal

from pydantic import BaseModel

from app.domain.ports import LogLine, NodeError

NodeStatus = Literal["succeeded", "failed", "skipped"]


class NodeExecution(BaseModel):
    node_id: str
    status: NodeStatus
    input: Any = None
    output: Any = None
    logs: list[LogLine] = []
    error: NodeError | None = None
    duration_ms: int = 0


class ExecutionRun(BaseModel):
    id: str
    status: Literal["succeeded", "failed"]
    nodes: list[NodeExecution]
    duration_ms: int
