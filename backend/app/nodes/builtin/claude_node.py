# ruff: noqa: E501
"""Ask Claude a question with the Anthropic Messages API. The key is a saved credential, never config text."""

import json
import re
import time
from typing import Any, ClassVar

from app.domain.nodes import NodeContext, NodeDefinition, NodeResult
from app.domain.ports import JsonValue, NodeError
from app.nodes.builtin.data_nodes import render_template
from app.nodes.builtin.http_request import HttpRequestNode

URL = "https://api.anthropic.com/v1/messages"
NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class ClaudeNode:
    definition: ClassVar[NodeDefinition] = NodeDefinition(
        type="ai.claude",
        title="Ask Claude",
        category="AI",
        description="Send a prompt to Claude. Your API key is read from a saved credential at run time. The prompt (with data from earlier nodes) is sent to Anthropic.",
        config_schema={
            "type": "object",
            "required": ["prompt"],
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "may contain {{ $.path }} placeholders",
                },
                "system": {"type": "string"},
                "model": {"type": "string", "default": "claude-sonnet-5-5"},
                "max_tokens": {"type": "integer", "minimum": 1, "maximum": 8192, "default": 1024},
                "credential": {"type": "string", "default": "anthropic"},
            },
        },
        default_config={
            "prompt": "Summarize: {{ $.text }}",
            "model": "claude-sonnet-5-5",
            "max_tokens": 1024,
            "credential": "anthropic",
        },
    )

    def __init__(self, http: HttpRequestNode) -> None:
        self.http = http

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        p: list[str] = []
        if not isinstance(config.get("prompt"), str) or not config["prompt"].strip():
            p.append("config.prompt must be a non-empty string")
        if not NAME.match(str(config.get("credential", "anthropic"))):
            p.append("config.credential must be a credential name")
        mt = config.get("max_tokens", 1024)
        if not isinstance(mt, int) or not 1 <= mt <= 8192:
            p.append("config.max_tokens must be between 1 and 8192")
        return p

    async def execute(
        self, ctx: NodeContext, input_data: JsonValue, config: dict[str, Any]
    ) -> NodeResult:
        start = time.monotonic()
        try:
            prompt = render_template(config["prompt"], input_data, escape=False, strict=False)
        except KeyError as e:
            return NodeResult(
                status="failed",
                output=None,
                logs=[],
                duration_ms=0,
                error=NodeError(type="transform_error", message=f"No value at {e.args[0]}"),
            )
        body: dict[str, Any] = {
            "model": config.get("model", "claude-sonnet-5-5"),
            "max_tokens": config.get("max_tokens", 1024),
            "messages": [{"role": "user", "content": prompt}],
        }
        if config.get("system"):
            body["system"] = config["system"]
        http_config = {
            "url": URL,
            "method": "POST",
            "headers": {
                "x-api-key": "{{credential:" + str(config.get("credential", "anthropic")) + "}}",
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            "body": json.dumps(body),
            "timeout_s": 30,
            "max_response_kb": 1024,
            "fail_on_error_status": True,
        }
        res = await self.http.execute(ctx, input_data, http_config)
        if res.status != "succeeded" or not isinstance(res.output, dict):
            return res
        data = res.output.get("body")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                data = None
        blocks = data.get("content") if isinstance(data, dict) else None
        if not isinstance(data, dict) or not isinstance(blocks, list):
            return NodeResult(
                status="failed",
                output=None,
                logs=res.logs,
                duration_ms=int((time.monotonic() - start) * 1000),
                error=NodeError(
                    type="http_error", message="Unexpected response from the Anthropic API"
                ),
            )
        text = "".join(
            b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"
        )
        return NodeResult(
            status="succeeded",
            output={
                "text": text,
                "model": data.get("model"),
                "usage": data.get("usage"),
                "stop_reason": data.get("stop_reason"),
            },
            logs=res.logs,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
