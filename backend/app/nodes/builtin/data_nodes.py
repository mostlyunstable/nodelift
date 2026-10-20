# ruff: noqa: E501
"""Data nodes that need no code execution: filter, text/HTML template, CSV, files and SQLite.

Files and databases are confined to one folder (`<data dir>/files`): absolute paths, `..` and symlinks that
leave it are refused. SQLite is read-only unless the node says otherwise, and cannot ATTACH other files.
"""

import asyncio
import csv
import html
import io
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, ClassVar

from app.domain.nodes import NodeContext, NodeDefinition, NodeResult
from app.domain.ports import JsonValue, LogLine, NodeError
from app.nodes.builtin.json_transform import _MISSING, parse_path, resolve

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 10_000


def _done(output: JsonValue, start: float, logs: list[LogLine] | None = None) -> NodeResult:
    return NodeResult(
        status="succeeded",
        output=output,
        logs=logs or [],
        duration_ms=int((time.monotonic() - start) * 1000),
    )


def _fail(kind: Any, message: str, start: float) -> NodeResult:
    return NodeResult(
        status="failed",
        output=None,
        logs=[],
        duration_ms=int((time.monotonic() - start) * 1000),
        error=NodeError(type=kind, message=message),
    )


def pick(data: Any, path: str) -> Any:
    return resolve(data, parse_path(path))


# ------------------------------------------------------------------------------------ filter
OPS = {"eq", "ne", "gt", "gte", "lt", "lte", "contains", "in", "exists", "not_exists"}


def _test(value: Any, op: str, expected: Any) -> bool:
    if op == "exists":
        return value is not _MISSING
    if op == "not_exists":
        return value is _MISSING
    if value is _MISSING:
        return False
    try:
        if op == "eq":
            return bool(value == expected)
        if op == "ne":
            return bool(value != expected)
        if op == "gt":
            return bool(value > expected)
        if op == "gte":
            return bool(value >= expected)
        if op == "lt":
            return bool(value < expected)
        if op == "lte":
            return bool(value <= expected)
        if op == "contains":
            return bool(expected in value)
        if op == "in":
            return bool(value in expected)
    except TypeError:
        return False
    return False


class FilterNode:
    definition: ClassVar[NodeDefinition] = NodeDefinition(
        type="data.filter",
        title="Filter list",
        category="Data",
        description="Keep the items of a list that match conditions. Each condition's path starts at the item ($).",
        config_schema={
            "type": "object",
            "required": ["where"],
            "properties": {
                "items_path": {"type": "string", "default": "$"},
                "match": {"enum": ["all", "any"], "default": "all"},
                "where": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["path", "op"],
                        "properties": {
                            "path": {"type": "string"},
                            "op": {"enum": sorted(OPS)},
                            "value": {},
                        },
                    },
                },
            },
        },
        default_config={
            "items_path": "$",
            "match": "all",
            "where": [{"path": "$.value", "op": "gt", "value": 0}],
        },
    )

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        problems: list[str] = []
        where = config.get("where")
        if not isinstance(where, list) or not where or len(where) > 20:
            return ["config.where must be a list of 1 to 20 conditions"]
        for i, c in enumerate(where):
            if (
                not isinstance(c, dict)
                or c.get("op") not in OPS
                or not isinstance(c.get("path"), str)
            ):
                problems.append(f"condition {i + 1} needs a path and one of {sorted(OPS)}")
                continue
            try:
                parse_path(c["path"])
            except ValueError as e:
                problems.append(f"condition {i + 1}: {e}")
        if config.get("match", "all") not in {"all", "any"}:
            problems.append("config.match must be 'all' or 'any'")
        try:
            parse_path(config.get("items_path", "$"))
        except ValueError as e:
            problems.append(f"items_path: {e}")
        return problems

    async def execute(
        self, ctx: NodeContext, input_data: JsonValue, config: dict[str, Any]
    ) -> NodeResult:
        start = time.monotonic()
        items = pick(input_data, config.get("items_path", "$"))
        if not isinstance(items, list):
            return _fail("transform_error", "The input at items_path is not a list", start)
        use_all = config.get("match", "all") == "all"
        kept = []
        for item in items:
            results = [
                _test(pick(item, c["path"]), c["op"], c.get("value")) for c in config["where"]
            ]
            if all(results) if use_all else any(results):
                kept.append(item)
        return _done({"items": kept, "kept": len(kept), "dropped": len(items) - len(kept)}, start)


# ---------------------------------------------------------------------------------- template
_PLACEHOLDER = re.compile(r"\{\{\s*(\$[^{}]*?)\s*\}\}")


def render_template(template: str, data: Any, escape: bool, strict: bool) -> str:
    def swap(m: re.Match[str]) -> str:
        value = pick(data, m.group(1))
        if value is _MISSING:
            if strict:
                raise KeyError(m.group(1))
            return ""
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return html.escape(text) if escape else text

    return _PLACEHOLDER.sub(swap, template)


class TemplateNode:
    definition: ClassVar[NodeDefinition] = NodeDefinition(
        type="text.template",
        title="Text / HTML template",
        category="Data",
        description="Fill {{ $.path }} placeholders from the input. No code runs. Tick 'Escape HTML' when building HTML.",
        config_schema={
            "type": "object",
            "required": ["template"],
            "properties": {
                "template": {"type": "string"},
                "escape_html": {"type": "boolean", "default": False},
                "strict": {"type": "boolean", "default": False},
            },
        },
        default_config={"template": "Hello {{ $.name }}", "escape_html": False, "strict": False},
    )

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        t = config.get("template")
        if not isinstance(t, str) or len(t) > 200_000:
            return ["config.template must be a string of at most 200,000 characters"]
        for m in _PLACEHOLDER.finditer(t):
            try:
                parse_path(m.group(1))
            except ValueError as e:
                return [f"placeholder {m.group(0)!r}: {e}"]
        return []

    async def execute(
        self, ctx: NodeContext, input_data: JsonValue, config: dict[str, Any]
    ) -> NodeResult:
        start = time.monotonic()
        try:
            text = render_template(
                config["template"],
                input_data,
                config.get("escape_html") is True,
                config.get("strict") is True,
            )
        except KeyError as e:
            return _fail("transform_error", f"The input has no value at {e.args[0]}", start)
        if len(text.encode()) > MAX_BYTES:
            return _fail("output_too_large", "The rendered text is larger than 5 MB", start)
        return _done({"text": text}, start)


# ------------------------------------------------------------------------------------- csv
class CsvNode:
    definition: ClassVar[NodeDefinition] = NodeDefinition(
        type="data.csv",
        title="CSV",
        category="Data",
        description="Parse CSV text into rows, or write a list of objects as CSV text.",
        config_schema={
            "type": "object",
            "required": ["mode"],
            "properties": {
                "mode": {"enum": ["parse", "write"]},
                "path": {
                    "type": "string",
                    "default": "$",
                    "description": "where the CSV text (parse) or the list (write) is in the input",
                },
                "delimiter": {"type": "string", "default": ","},
                "header": {"type": "boolean", "default": True},
            },
        },
        default_config={"mode": "parse", "path": "$", "delimiter": ",", "header": True},
    )

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        p: list[str] = []
        if config.get("mode") not in {"parse", "write"}:
            p.append("config.mode must be 'parse' or 'write'")
        d = config.get("delimiter", ",")
        if not isinstance(d, str) or len(d) != 1 or d in '\r\n"':
            p.append("config.delimiter must be a single character")
        try:
            parse_path(config.get("path", "$"))
        except ValueError as e:
            p.append(f"path: {e}")
        return p

    async def execute(
        self, ctx: NodeContext, input_data: JsonValue, config: dict[str, Any]
    ) -> NodeResult:
        start = time.monotonic()
        src = pick(input_data, config.get("path", "$"))
        delim = config.get("delimiter", ",")
        header = config.get("header", True) is not False
        if config["mode"] == "parse":
            if not isinstance(src, str):
                return _fail("transform_error", "The input at path is not CSV text", start)
            if len(src.encode()) > MAX_BYTES:
                return _fail("invalid_config", "CSV text is larger than 5 MB", start)
            reader = csv.reader(io.StringIO(src), delimiter=delim)
            rows = [r for r in reader]
            if len(rows) > 100_000:
                return _fail("invalid_config", "More than 100,000 rows", start)
            if header and rows:
                names = rows[0]
                out: list[Any] = [dict(zip(names, r, strict=False)) for r in rows[1:]]
            else:
                out = rows
            return _done({"rows": out, "count": len(out)}, start)
        if not isinstance(src, list) or not all(isinstance(r, dict) for r in src):
            return _fail("transform_error", "The input at path is not a list of objects", start)
        cols: list[str] = []
        for r in src:
            for k in r:
                if k not in cols:
                    cols.append(k)
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=delim, lineterminator="\n")
        if header:
            w.writerow(cols)
        for r in src:
            w.writerow(
                [
                    ""
                    if r.get(c) is None
                    else (json.dumps(r[c]) if isinstance(r[c], (dict, list)) else r[c])
                    for c in cols
                ]
            )
        return _done({"csv": buf.getvalue(), "rows": len(src)}, start)


# ----------------------------------------------------------------------------------- files
def safe_path(base: Path, rel: str) -> Path:
    if (
        not isinstance(rel, str)
        or not rel
        or rel.startswith(("/", "~"))
        or "\x00" in rel
        or "\\" in rel
    ):
        raise ValueError("path must be relative, inside the files folder")
    root = base.resolve()
    target = (root / rel).resolve()
    if root not in target.parents:
        raise ValueError("path leaves the files folder")
    return target


class FileReadNode:
    definition: ClassVar[NodeDefinition] = NodeDefinition(
        type="file.read",
        title="Read file",
        category="Files",
        description="Read a text file from Nodecraft's files folder (nothing outside it).",
        config_schema={
            "type": "object",
            "required": ["path"],
            "properties": {"path": {"type": "string"}},
        },
        default_config={"path": "input.txt"},
    )

    def __init__(self, base: Path) -> None:
        self.base = base

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        try:
            safe_path(self.base, config.get("path", ""))
        except ValueError as e:
            return [str(e)]
        return []

    async def execute(
        self, ctx: NodeContext, input_data: JsonValue, config: dict[str, Any]
    ) -> NodeResult:
        start = time.monotonic()
        try:
            target = safe_path(self.base, config["path"])
            if target.stat().st_size > MAX_BYTES:
                return _fail("invalid_config", "The file is larger than 5 MB", start)
            text = target.read_text(encoding="utf-8")
        except ValueError as e:
            return _fail("invalid_config", str(e), start)
        except FileNotFoundError:
            return _fail(
                "invalid_config", f"No file named {config['path']!r} in the files folder", start
            )
        except (OSError, UnicodeDecodeError) as e:
            return _fail("runtime_error", f"Could not read the file: {type(e).__name__}", start)
        return _done({"path": config["path"], "text": text, "bytes": len(text.encode())}, start)


class FileWriteNode:
    definition: ClassVar[NodeDefinition] = NodeDefinition(
        type="file.write",
        title="Write file",
        category="Files",
        description="Write text to a file in Nodecraft's files folder (nothing outside it).",
        config_schema={
            "type": "object",
            "required": ["path"],
            "properties": {
                "path": {"type": "string"},
                "content_path": {"type": "string", "default": "$"},
                "append": {"type": "boolean", "default": False},
            },
        },
        default_config={"path": "output.txt", "content_path": "$", "append": False},
    )

    def __init__(self, base: Path) -> None:
        self.base = base

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        try:
            safe_path(self.base, config.get("path", ""))
            parse_path(config.get("content_path", "$"))
        except ValueError as e:
            return [str(e)]
        return []

    async def execute(
        self, ctx: NodeContext, input_data: JsonValue, config: dict[str, Any]
    ) -> NodeResult:
        start = time.monotonic()
        value = pick(input_data, config.get("content_path", "$"))
        if value is _MISSING:
            return _fail("transform_error", "The input has no value at content_path", start)
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
        if len(text.encode()) > MAX_BYTES:
            return _fail("invalid_config", "Content is larger than 5 MB", start)
        try:
            target = safe_path(self.base, config["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a" if config.get("append") else "w", encoding="utf-8") as fh:
                fh.write(text)
        except ValueError as e:
            return _fail("invalid_config", str(e), start)
        except OSError as e:
            return _fail("runtime_error", f"Could not write the file: {type(e).__name__}", start)
        return _done({"path": config["path"], "bytes": len(text.encode())}, start)


# ---------------------------------------------------------------------------------- sqlite
class SqliteQueryNode:
    definition: ClassVar[NodeDefinition] = NodeDefinition(
        type="db.sqlite",
        title="SQLite query",
        category="Files",
        description="Run one SQL statement on a SQLite file in the files folder. Read-only unless you allow writes.",
        config_schema={
            "type": "object",
            "required": ["db", "sql"],
            "properties": {
                "db": {"type": "string"},
                "sql": {"type": "string"},
                "params": {"type": "array"},
                "allow_write": {"type": "boolean", "default": False},
            },
        },
        default_config={
            "db": "data.db",
            "sql": "SELECT 1 AS one",
            "params": [],
            "allow_write": False,
        },
    )

    def __init__(self, base: Path) -> None:
        self.base = base

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        p: list[str] = []
        try:
            safe_path(self.base, config.get("db", ""))
        except ValueError as e:
            p.append(str(e))
        sql = config.get("sql")
        if not isinstance(sql, str) or not sql.strip() or len(sql) > 20_000:
            p.append("config.sql must be a non-empty string")
        if not isinstance(config.get("params", []), list):
            p.append("config.params must be a list")
        return p

    @staticmethod
    def _authorizer(action: int, a: Any, b: Any, c: Any, d: Any) -> int:
        if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH):
            return sqlite3.SQLITE_DENY  # would open files outside the folder
        return sqlite3.SQLITE_OK

    def _run(self, config: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        target = safe_path(self.base, config["db"])
        write = config.get("allow_write") is True
        if write:
            target.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(target))
        else:
            if not target.is_file():
                raise FileNotFoundError(config["db"])
            conn = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
        deadline = time.monotonic() + timeout_s
        try:
            conn.set_authorizer(self._authorizer)
            conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
            conn.row_factory = sqlite3.Row
            cur = conn.execute(config["sql"], config.get("params", []))
            if cur.description:
                rows = [dict(r) for r in cur.fetchmany(MAX_ROWS + 1)]
                truncated = len(rows) > MAX_ROWS
                return {
                    "rows": rows[:MAX_ROWS],
                    "count": min(len(rows), MAX_ROWS),
                    "truncated": truncated,
                }
            conn.commit()
            return {"rows_affected": cur.rowcount}
        finally:
            conn.close()

    async def execute(
        self, ctx: NodeContext, input_data: JsonValue, config: dict[str, Any]
    ) -> NodeResult:
        start = time.monotonic()
        try:
            out = await asyncio.wait_for(
                asyncio.to_thread(self._run, config, ctx.timeout_s), ctx.timeout_s + 1
            )
        except ValueError as e:
            return _fail("invalid_config", str(e), start)
        except FileNotFoundError:
            return _fail(
                "invalid_config", f"No database named {config['db']!r} in the files folder", start
            )
        except TimeoutError:
            return _fail("timeout", f"The query exceeded {ctx.timeout_s:g}s", start)
        except sqlite3.Error as e:
            msg = str(e)
            if "interrupted" in msg:
                return _fail("timeout", f"The query exceeded {ctx.timeout_s:g}s", start)
            if "not authorized" in msg:
                return _fail(
                    "blocked_request",
                    "That statement is not allowed (ATTACH/DETACH would leave the files folder)",
                    start,
                )
            return _fail("runtime_error", f"SQLite: {msg}", start)
        return _done(out, start)
