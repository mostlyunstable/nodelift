import importlib
import logging
from pathlib import Path

from app.domain.nodes import NodeRegistry
from app.domain.ports import CodeRunner
from app.nodes.builtin.branch import BranchNode
from app.nodes.builtin.claude_node import ClaudeNode
from app.nodes.builtin.code_python import CodePythonNode
from app.nodes.builtin.data_nodes import (
    CsvNode,
    FileListNode,
    FileReadNode,
    FileWriteNode,
    FilterNode,
    SqliteQueryNode,
    TemplateNode,
)
from app.nodes.builtin.http_request import HttpRequestNode
from app.nodes.builtin.json_transform import JsonTransformNode

log = logging.getLogger("nodecraft.nodes")


def default_registry(
    runner: CodeRunner, allow_private_http: bool = False, files_dir: Path | None = None
) -> NodeRegistry:
    """Built-in node types. Registration is explicit; there is no auto-discovery."""
    registry = NodeRegistry()
    registry.register(CodePythonNode(runner))
    registry.register(JsonTransformNode())
    registry.register(BranchNode())
    http = HttpRequestNode(allow_private=allow_private_http)
    registry.register(http)
    registry.register(FilterNode())
    registry.register(TemplateNode())
    registry.register(CsvNode())
    registry.register(ClaudeNode(http))
    base = files_dir or Path.home() / ".nodecraft" / "files"
    registry.register(FileListNode(base))
    registry.register(FileReadNode(base))
    registry.register(FileWriteNode(base))
    registry.register(SqliteQueryNode(base))
    return registry


def load_plugins(registry: NodeRegistry, modules: list[str]) -> None:
    """Import each module and call its `register(registry)`.

    Plugins run inside the server process with full privileges. Only list modules you trust and
    control; this is operator configuration (NODECRAFT_NODE_PLUGINS), never user input.
    """
    for name in modules:
        module = importlib.import_module(name)
        register = getattr(module, "register", None)
        if not callable(register):
            raise RuntimeError(f"node plugin {name!r} has no register(registry) function")
        register(registry)
        log.info("loaded node plugin %s", name)
