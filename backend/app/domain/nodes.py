"""Node contract. A node type is a NodeDefinition (metadata) plus a NodeImpl (behaviour)."""

import asyncio
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol

from pydantic import BaseModel

from app.domain.ports import CodeRunResult, JsonValue
from app.domain.secrets import SecretResolver

NodeResult = CodeRunResult  # status, output, logs, error, duration_ms


class Port(BaseModel):
    name: str
    description: str = ""


class NodeDefinition(BaseModel):
    """Serialised to the UI palette. `config_schema` is JSON Schema, for documentation and forms."""

    type: str  # stable id, e.g. "http.request"
    version: int = 1
    title: str
    category: str
    description: str = ""
    config_schema: dict[str, Any] = {}
    default_config: dict[str, Any] = {}
    inputs: list[Port] = [Port(name="in")]
    outputs: list[Port] = [Port(name="out")]


@dataclass
class NodeContext:
    timeout_s: float
    cancel: asyncio.Event | None = None
    secrets: SecretResolver | None = None  # resolves {{credential:NAME}} for nodes that accept them


class NodeImpl(Protocol):
    definition: ClassVar[NodeDefinition]

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        """Static checks only (no network or disk). Returns human-readable problems."""
        ...

    async def execute(
        self, ctx: NodeContext, input_data: JsonValue, config: dict[str, Any]
    ) -> NodeResult:
        """Run once. Report failures as `NodeResult(status="failed", error=...)`; do not raise."""
        ...


class NodeRegistry:
    def __init__(self) -> None:
        self._impls: dict[str, NodeImpl] = {}

    def register(self, impl: NodeImpl) -> None:
        t = impl.definition.type
        if t in self._impls:
            raise ValueError(f"node type {t!r} is already registered")
        self._impls[t] = impl

    def get(self, node_type: str) -> NodeImpl | None:
        return self._impls.get(node_type)

    def definitions(self) -> list[NodeDefinition]:
        return [i.definition for i in self._impls.values()]
