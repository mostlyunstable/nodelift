from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from app.domain.ports import LogLine, NodeError

NodeStatus = Literal["succeeded", "failed", "skipped"]
RunStatus = Literal["running", "succeeded", "failed"]


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
    status: RunStatus
    nodes: list[NodeExecution]
    duration_ms: int


class RunEvent(BaseModel):
    run_id: str
    seq: int  # monotonic per run; the SSE event id, used to resume after a disconnect
    type: str
    created_at: datetime
    payload: dict[str, Any] = {}


class RunObserver(Protocol):
    """Hooks the engine calls while executing. Implemented by the service (persist + notify)."""

    async def node_started(self, node_id: str) -> None: ...
    async def node_finished(self, record: NodeExecution) -> None: ...
