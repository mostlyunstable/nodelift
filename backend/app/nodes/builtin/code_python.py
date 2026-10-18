from typing import Any, ClassVar

from app.domain.nodes import NodeContext, NodeDefinition, NodeResult
from app.domain.ports import CodeRunner, JsonValue

DEFAULT_SOURCE = 'def main(input_data):\n    return {"message": "Hello from Nodecraft"}\n'


class CodePythonNode:
    definition: ClassVar[NodeDefinition] = NodeDefinition(
        type="code.python",
        title="Python code",
        category="Code",
        description="Runs main(input_data) in a separate process (trusted local mode, no sandbox).",
        config_schema={
            "type": "object",
            "required": ["source"],
            "properties": {"source": {"type": "string", "title": "Python source"}},
        },
        default_config={"source": DEFAULT_SOURCE},
    )

    def __init__(self, runner: CodeRunner) -> None:
        self.runner = runner

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        return [] if isinstance(config.get("source"), str) else ["config.source must be a string"]

    async def execute(
        self, ctx: NodeContext, input_data: JsonValue, config: dict[str, Any]
    ) -> NodeResult:
        return await self.runner.run(config["source"], input_data, ctx.timeout_s, ctx.cancel)
