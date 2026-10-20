"""If/else routing. The input passes through unchanged on the `true` or `false` port."""

import time
from typing import Any, ClassVar

from app.domain.nodes import NodeContext, NodeDefinition, NodeResult, Port
from app.domain.ports import JsonValue, NodeError
from app.nodes.builtin.json_transform import _MISSING, parse_path, resolve

OPERATORS = {"truthy", "exists", "eq", "ne", "gt", "gte", "lt", "lte", "contains"}
NEEDS_VALUE = {"eq", "ne", "gt", "gte", "lt", "lte", "contains"}


def _is_number(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def _equal(a: Any, b: Any) -> bool:
    """JSON equality that does not confuse 1 with True or "1"."""
    if _is_number(a) and _is_number(b):
        return bool(a == b)
    return type(a) is type(b) and bool(a == b)


def evaluate(op: str, found: Any, expected: Any) -> bool:
    """A missing value is just "no" (use `exists`); mismatched types never match."""
    if op == "exists":
        return found is not _MISSING
    if found is _MISSING:
        return False
    if op == "truthy":
        return bool(found)
    if op == "eq":
        return _equal(found, expected)
    if op == "ne":
        return not _equal(found, expected)
    if op in ("gt", "gte", "lt", "lte"):
        if not (_is_number(found) and _is_number(expected)):
            return False
        return bool(
            {
                "gt": found > expected,
                "gte": found >= expected,
                "lt": found < expected,
                "lte": found <= expected,
            }[op]
        )
    if op == "contains":
        if isinstance(found, str):
            return isinstance(expected, str) and expected in found
        if isinstance(found, list):
            return any(_equal(item, expected) for item in found)
        if isinstance(found, dict):
            return isinstance(expected, str) and expected in found
    return False


class BranchNode:
    definition: ClassVar[NodeDefinition] = NodeDefinition(
        type="logic.branch",
        title="Branch (if / else)",
        category="Logic",
        description="Sends the input down the `true` or `false` connection by a condition.",
        config_schema={
            "type": "object",
            "required": ["path", "operator"],
            "properties": {
                "path": {"type": "string", "description": "e.g. $.order.total"},
                "operator": {"enum": sorted(OPERATORS)},
                "value": {"description": "what to compare with"},
                "strict": {"type": "boolean", "default": False},
            },
        },
        default_config={"path": "$", "operator": "truthy"},
        outputs=[Port(name="true"), Port(name="false")],
    )

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        problems: list[str] = []
        path = config.get("path")
        if not isinstance(path, str):
            problems.append("config.path must be a string like $.order.total")
        else:
            try:
                parse_path(path)
            except ValueError as e:
                problems.append(f"config.path: {e}")
        op = config.get("operator")
        if op not in OPERATORS:
            problems.append(f"config.operator must be one of {sorted(OPERATORS)}")
        elif op in NEEDS_VALUE and "value" not in config:
            problems.append(f"operator {op!r} needs config.value to compare with")
        if "strict" in config and not isinstance(config["strict"], bool):
            problems.append("config.strict must be a boolean")
        return problems

    async def execute(
        self, ctx: NodeContext, input_data: JsonValue, config: dict[str, Any]
    ) -> NodeResult:
        start = time.monotonic()
        found = resolve(input_data, parse_path(config["path"]))
        if found is _MISSING and config.get("strict") and config["operator"] != "exists":
            return NodeResult(
                status="failed",
                duration_ms=int((time.monotonic() - start) * 1000),
                error=NodeError(type="transform_error", message=f"{config['path']} not found"),
            )
        taken = evaluate(config["operator"], found, config.get("value"))
        return NodeResult(
            status="succeeded",
            output=input_data,
            activated_ports=["true" if taken else "false"],
            duration_ms=int((time.monotonic() - start) * 1000),
        )
