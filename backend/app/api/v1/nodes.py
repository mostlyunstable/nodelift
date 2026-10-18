from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.errors import AppError
from app.domain.nodes import NodeContext, NodeDefinition, NodeRegistry
from app.domain.ports import CodeRunResult, JsonValue

router = APIRouter(prefix="/nodes", tags=["nodes"])


def get_registry(request: Request) -> NodeRegistry:
    registry: NodeRegistry = request.app.state.registry
    return registry


Registry = Annotated[NodeRegistry, Depends(get_registry)]


class NodeTestRequest(BaseModel):
    type: str
    config: dict[str, Any] = {}
    input: JsonValue = None
    timeout_ms: int = Field(default=5000, ge=100, le=30_000)


class CodeTestRequest(BaseModel):
    source: str = Field(max_length=200_000)
    input: JsonValue = None
    timeout_ms: int = Field(default=5000, ge=100, le=30_000)


@router.get("/definitions", response_model=list[NodeDefinition])
def list_definitions(registry: Registry) -> list[NodeDefinition]:
    return registry.definitions()


@router.post("/test", response_model=CodeRunResult)
async def test_node(req: NodeTestRequest, registry: Registry) -> CodeRunResult:
    """Run one node of any registered type in isolation."""
    impl = registry.get(req.type)
    if impl is None:
        raise AppError(422, "unknown_node_type", f"Unknown node type {req.type}")
    problems = impl.validate_config(req.config)
    if problems:
        raise AppError(
            422, "validation_failed", "Invalid node config",
            [{"code": "invalid_config", "message": p} for p in problems],
        )  # fmt: skip
    return await impl.execute(NodeContext(req.timeout_ms / 1000), req.input, req.config)


@router.post("/code/test", response_model=CodeRunResult)
async def test_code(req: CodeTestRequest, registry: Registry) -> CodeRunResult:
    """Kept for compatibility; equivalent to /nodes/test with type code.python."""
    impl = registry.get("code.python")
    assert impl is not None
    return await impl.execute(NodeContext(req.timeout_ms / 1000), req.input, {"source": req.source})
