"""Framework-free result types shared by the runtime and the API."""

import asyncio
from typing import Any, Literal, Protocol

from pydantic import BaseModel

JsonValue = Any  # JSON-compatible value (validated at the runtime boundary)

ErrorType = Literal[
    "syntax_error",
    "missing_main",
    "runtime_error",
    "invalid_output",
    "output_too_large",
    "timeout",
    "cancelled",
    "invalid_config",
    "transform_error",
    "blocked_request",
    "network_error",
    "http_error",
    "response_too_large",
    "missing_credential",
    "secrets_unavailable",
    "worker_crashed",
]


class LogLine(BaseModel):
    stream: Literal["stdout", "stderr"]
    text: str


class NodeError(BaseModel):
    type: ErrorType
    message: str
    line: int | None = None
    column: int | None = None
    traceback: str | None = None


class CodeRunResult(BaseModel):
    status: Literal["succeeded", "failed"]
    output: JsonValue = None
    logs: list[LogLine] = []
    duration_ms: int
    error: NodeError | None = None
    activated_ports: list[str] | None = None  # None: every output port; else only these


class CodeRunner(Protocol):
    async def run(
        self,
        source: str,
        input_data: JsonValue,
        timeout_s: float,
        cancel: asyncio.Event | None = None,
    ) -> CodeRunResult: ...
