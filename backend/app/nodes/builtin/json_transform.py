"""Declarative JSON reshaping. No code is executed, so it is safe, fast and idempotent.

config.mapping maps output keys to either a path ("$.user.items[0].name") or {"literal": value}.
"""

import re
import time
from typing import Any, ClassVar

from app.domain.nodes import NodeContext, NodeDefinition, NodeResult
from app.domain.ports import JsonValue, NodeError

MAX_KEYS = 100
_TOKEN = re.compile(r"""\.([A-Za-z_][\w-]*)|\[(-?\d+)\]|\["([^"\\]*)"\]""")
_MISSING = object()


def parse_path(path: str) -> list[str | int]:
    if not path.startswith("$"):
        raise ValueError("path must start with $")
    rest, parts, pos = path[1:], [], 0
    while pos < len(rest):
        m = _TOKEN.match(rest, pos)
        if not m:
            raise ValueError(f"unexpected character at position {pos + 1}")
        name, index, quoted = m.groups()
        parts.append(name if name is not None else int(index) if index is not None else quoted)
        pos = m.end()
    return parts


def resolve(data: Any, parts: list[str | int]) -> Any:
    cur = data
    for part in parts:
        if isinstance(part, int):
            if not isinstance(cur, list) or not -len(cur) <= part < len(cur):
                return _MISSING
            cur = cur[part]
        else:
            if not isinstance(cur, dict) or part not in cur:
                return _MISSING
            cur = cur[part]
    return cur


class JsonTransformNode:
    definition: ClassVar[NodeDefinition] = NodeDefinition(
        type="transform.json",
        title="JSON transform",
        category="Data",
        description="Build a new object from the input using $.paths and literals.",
        config_schema={
            "type": "object",
            "required": ["mapping"],
            "properties": {
                "mapping": {"type": "object", "additionalProperties": True},
                "strict": {"type": "boolean", "default": False},
            },
        },
        default_config={"mapping": {"value": "$"}, "strict": False},
    )

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        mapping = config.get("mapping")
        if not isinstance(mapping, dict) or not mapping:
            return ["config.mapping must be a non-empty object"]
        if len(mapping) > MAX_KEYS:
            return [f"config.mapping has more than {MAX_KEYS} keys"]
        problems: list[str] = []
        for key, spec in mapping.items():
            if isinstance(spec, str):
                try:
                    parse_path(spec)
                except ValueError as e:
                    problems.append(f"mapping[{key!r}]: {e}")
            elif not (isinstance(spec, dict) and set(spec) == {"literal"}):
                problems.append(f'mapping[{key!r}] must be a path string or {{"literal": value}}')
        if "strict" in config and not isinstance(config["strict"], bool):
            problems.append("config.strict must be a boolean")
        return problems

    async def execute(
        self, ctx: NodeContext, input_data: JsonValue, config: dict[str, Any]
    ) -> NodeResult:
        start = time.monotonic()
        out: dict[str, Any] = {}
        for key, spec in config["mapping"].items():
            if isinstance(spec, dict):
                out[key] = spec["literal"]
                continue
            value = resolve(input_data, parse_path(spec))
            if value is _MISSING:
                if config.get("strict"):
                    return NodeResult(
                        status="failed",
                        duration_ms=int((time.monotonic() - start) * 1000),
                        error=NodeError(
                            type="transform_error", message=f"{spec} not found (for {key!r})"
                        ),
                    )
                value = None
            out[key] = value
        return NodeResult(
            status="succeeded", output=out, duration_ms=int((time.monotonic() - start) * 1000)
        )
