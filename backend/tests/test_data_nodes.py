# ruff: noqa: E501
import asyncio
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from app.domain.nodes import NodeContext, NodeResult
from app.domain.ports import NodeError
from app.nodes import default_registry
from app.nodes.builtin.claude_node import ClaudeNode
from app.nodes.builtin.data_nodes import (
    CsvNode,
    FileReadNode,
    FileWriteNode,
    FilterNode,
    SqliteQueryNode,
    TemplateNode,
    safe_path,
)
from app.nodes.builtin.http_request import HttpRequestNode
from app.runtime.subprocess_runner import SubprocessRunner

CTX = NodeContext(timeout_s=5)


def run(node: Any, data: Any, config: dict[str, Any]) -> NodeResult:
    problems = node.validate_config(config)
    assert problems == [], problems
    return asyncio.run(node.execute(CTX, data, config))


def fails(node: Any, data: Any, config: dict[str, Any]) -> NodeError:
    res = asyncio.run(node.execute(CTX, data, config))
    assert res.status == "failed" and res.error is not None, res
    return res.error


# ---- registry ----------------------------------------------------------------------------------
def test_all_new_types_are_registered_with_definitions(tmp_path: Path) -> None:
    reg = default_registry(SubprocessRunner(), files_dir=tmp_path)
    types = {d.type for d in reg.definitions()}
    assert {
        "data.filter",
        "text.template",
        "data.csv",
        "file.read",
        "file.write",
        "db.sqlite",
        "ai.claude",
    } <= types


# ---- filter ------------------------------------------------------------------------------------
ITEMS = {
    "people": [
        {"n": "a", "age": 30, "tags": ["x"]},
        {"n": "b", "age": 17, "tags": []},
        {"n": "c", "tags": ["x", "y"]},
    ]
}


def test_filter_all_any_and_missing_fields() -> None:
    f = FilterNode()
    out = run(
        f, ITEMS, {"items_path": "$.people", "where": [{"path": "$.age", "op": "gte", "value": 18}]}
    ).output
    assert [i["n"] for i in out["items"]] == ["a"] and (out["kept"], out["dropped"]) == (
        1,
        2,
    )  # c has no age: not kept
    both = run(
        f,
        ITEMS,
        {
            "items_path": "$.people",
            "match": "all",
            "where": [
                {"path": "$.age", "op": "exists"},
                {"path": "$.tags", "op": "contains", "value": "x"},
            ],
        },
    ).output
    assert [i["n"] for i in both["items"]] == ["a"]
    either = run(
        f,
        ITEMS,
        {
            "items_path": "$.people",
            "match": "any",
            "where": [
                {"path": "$.age", "op": "lt", "value": 18},
                {"path": "$.age", "op": "not_exists"},
            ],
        },
    ).output
    assert [i["n"] for i in either["items"]] == ["b", "c"]


def test_filter_rejects_bad_config_and_non_lists() -> None:
    f = FilterNode()
    assert (
        f.validate_config({"where": []})
        and f.validate_config({"where": [{"path": "age", "op": "eq"}]})
        and f.validate_config({"where": [{"path": "$.a", "op": "nope"}]})
    )
    assert (
        fails(f, {"x": 1}, {"items_path": "$.x", "where": [{"path": "$", "op": "exists"}]}).type
        == "transform_error"
    )
    assert (
        run(f, [{"a": "x"}], {"where": [{"path": "$.a", "op": "gt", "value": 3}]}).output["kept"]
        == 0
    )  # str > int is a type error: not a match, not a crash


# ---- template ----------------------------------------------------------------------------------
def test_template_fills_placeholders_and_escapes_html_on_request() -> None:
    t = TemplateNode()
    data = {"name": "<b>Ann</b>", "n": 3, "obj": {"k": 1}}
    assert (
        run(t, data, {"template": "Hi {{ $.name }} #{{$.n}} {{ $.obj }} [{{ $.nope }}]"}).output[
            "text"
        ]
        == 'Hi <b>Ann</b> #3 {"k": 1} []'
    )
    assert (
        run(t, data, {"template": "<p>{{ $.name }}</p>", "escape_html": True}).output["text"]
        == "<p>&lt;b&gt;Ann&lt;/b&gt;</p>"
    )
    assert fails(t, data, {"template": "{{ $.nope }}", "strict": True}).type == "transform_error"
    assert t.validate_config({"template": "{{ $..bad }}"})


def test_template_runs_no_code() -> None:
    out = run(
        TemplateNode(),
        {"a": "x"},
        {"template": "{{ __import__('os').system('echo pwned') }} {{ $.a }}"},
    ).output
    assert (
        out["text"] == "{{ __import__('os').system('echo pwned') }} x"
    )  # not a $ path, so left as plain text


# ---- csv ---------------------------------------------------------------------------------------
def test_csv_round_trip_and_quoting() -> None:
    c = CsvNode()
    parsed = run(
        c, {"t": 'name,note\nAnn,"a, b"\nBob,"say ""hi"""\n'}, {"mode": "parse", "path": "$.t"}
    ).output
    assert parsed["rows"] == [{"name": "Ann", "note": "a, b"}, {"name": "Bob", "note": 'say "hi"'}]
    written = run(c, {"r": parsed["rows"]}, {"mode": "write", "path": "$.r"}).output
    assert (
        run(c, {"t": written["csv"]}, {"mode": "parse", "path": "$.t"}).output["rows"]
        == parsed["rows"]
    )
    assert run(c, "a;b\n1;2\n", {"mode": "parse", "delimiter": ";", "header": False}).output[
        "rows"
    ] == [["a", "b"], ["1", "2"]]
    assert fails(c, {"t": 5}, {"mode": "parse", "path": "$.t"}).type == "transform_error"
    assert c.validate_config({"mode": "parse", "delimiter": "ab"})


# ---- files stay inside the folder ------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["/etc/passwd", "../x", "a/../../x", "~/x", "a\\b", "", "x\x00y"])
def test_safe_path_refuses_escapes(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError):
        safe_path(tmp_path, bad)


def test_file_nodes_read_write_append(tmp_path: Path) -> None:
    w, r = FileWriteNode(tmp_path), FileReadNode(tmp_path)
    assert run(w, {"msg": "hello"}, {"path": "out/a.txt", "content_path": "$.msg"}).output == {
        "path": "out/a.txt",
        "bytes": 5,
    }
    run(w, {"msg": " world"}, {"path": "out/a.txt", "content_path": "$.msg", "append": True})
    assert run(r, None, {"path": "out/a.txt"}).output["text"] == "hello world"
    run(w, {"a": 1}, {"path": "j.json"})  # non-strings are written as JSON
    assert json.loads((tmp_path / "j.json").read_text()) == {"a": 1}
    assert fails(r, None, {"path": "missing.txt"}).type == "invalid_config"
    assert fails(w, {}, {"path": "x.txt", "content_path": "$.nope"}).type == "transform_error"


def test_file_nodes_cannot_follow_a_symlink_out_of_the_folder(tmp_path: Path) -> None:
    base, outside = tmp_path / "files", tmp_path / "secret.txt"
    base.mkdir()
    outside.write_text("top secret")
    os.symlink(outside, base / "link.txt")
    assert (
        "leaves the files folder" in fails(FileReadNode(base), None, {"path": "link.txt"}).message
    )
    assert (
        fails(FileWriteNode(base), {"a": "x"}, {"path": "link.txt", "content_path": "$.a"}).type
        == "invalid_config"
    )
    assert outside.read_text() == "top secret"


# ---- sqlite ------------------------------------------------------------------------------------
@pytest.fixture
def db(tmp_path: Path) -> Path:
    con = sqlite3.connect(tmp_path / "d.db")
    con.execute("create table t (id integer, name text)")
    con.executemany("insert into t values (?, ?)", [(1, "a"), (2, "b"), (3, "c")])
    con.commit()
    con.close()
    return tmp_path


def test_sqlite_reads_with_parameters_and_is_read_only_by_default(db: Path) -> None:
    n = SqliteQueryNode(db)
    out = run(
        n, None, {"db": "d.db", "sql": "select * from t where id > ? order by id", "params": [1]}
    ).output
    assert (
        out["rows"] == [{"id": 2, "name": "b"}, {"id": 3, "name": "c"}]
        and out["truncated"] is False
    )
    err = fails(n, None, {"db": "d.db", "sql": "delete from t"})
    assert err.type == "runtime_error" and "readonly" in err.message.lower()
    assert (
        len(run(n, None, {"db": "d.db", "sql": "select * from t"}).output["rows"]) == 3
    )  # nothing was deleted


def test_sqlite_writes_only_when_allowed_and_cannot_attach_other_files(
    db: Path, tmp_path: Path
) -> None:
    n = SqliteQueryNode(db)
    assert run(
        n, None, {"db": "d.db", "sql": "insert into t values (4, 'd')", "allow_write": True}
    ).output == {"rows_affected": 1}
    other = tmp_path.parent / f"other-{os.getpid()}.db"
    sqlite3.connect(other).close()
    for write in (False, True):
        err = fails(
            n, None, {"db": "d.db", "sql": f"attach database '{other}' as o", "allow_write": write}
        )
        assert err.type == "blocked_request"


def test_sqlite_row_cap_and_path_confinement(db: Path) -> None:
    n = SqliteQueryNode(db)
    out = run(
        n,
        None,
        {
            "db": "d.db",
            "sql": "with recursive c(x) as (select 1 union all select x+1 from c where x < 20000) select x from c",
        },
    ).output
    assert out["count"] == 10_000 and out["truncated"] is True
    assert n.validate_config({"db": "../d.db", "sql": "select 1"})
    assert fails(n, None, {"db": "nope.db", "sql": "select 1"}).type == "invalid_config"


def test_sqlite_infinite_query_is_stopped_by_the_time_limit(db: Path) -> None:
    n = SqliteQueryNode(db)
    ctx = NodeContext(timeout_s=1)
    res = asyncio.run(
        n.execute(
            ctx,
            None,
            {
                "db": "d.db",
                "sql": "with recursive c(x) as (select 1 union all select x+1 from c) select count(*) from c",
            },
        )
    )
    assert res.status == "failed" and res.error is not None and res.error.type == "timeout"


# ---- claude --------------------------------------------------------------------------------------------
class FakeHttp(HttpRequestNode):
    def __init__(self) -> None:
        super().__init__()
        self.seen: dict[str, Any] = {}

    async def execute(
        self, ctx: NodeContext, input_data: Any, config: dict[str, Any]
    ) -> NodeResult:
        self.seen = config
        return NodeResult(
            status="succeeded", duration_ms=1, logs=[],
            output={"status": 200, "ok": True, "headers": {}, "body": {"content": [{"type": "text", "text": "A summary."}], "model": "claude-sonnet-5-5", "usage": {"input_tokens": 5}, "stop_reason": "end_turn"}},
        )  # fmt: skip


def test_claude_node_builds_the_request_with_a_credential_reference_not_a_key() -> None:
    http = FakeHttp()
    node = ClaudeNode(http)
    res = run(
        node,
        {"text": "long text"},
        {
            "prompt": "Summarize: {{ $.text }}",
            "system": "Be brief.",
            "credential": "my-key",
            "max_tokens": 200,
        },
    )
    assert res.output == {
        "text": "A summary.",
        "model": "claude-sonnet-5-5",
        "usage": {"input_tokens": 5},
        "stop_reason": "end_turn",
    }
    seen = http.seen
    assert seen["url"] == "https://api.anthropic.com/v1/messages" and seen["method"] == "POST"
    assert (
        seen["headers"]["x-api-key"] == "{{credential:my-key}}"
    )  # resolved (and masked) by the HTTP node at run time
    body = json.loads(seen["body"])
    assert (
        body["messages"] == [{"role": "user", "content": "Summarize: long text"}]
        and body["system"] == "Be brief."
        and body["max_tokens"] == 200
    )
    assert (
        node.validate_config({"prompt": ""})
        and node.validate_config({"prompt": "x", "credential": "bad name!"})
        and node.validate_config({"prompt": "x", "max_tokens": 99999})
    )


def test_claude_node_passes_through_http_failures() -> None:
    class Failing(HttpRequestNode):
        async def execute(
            self, ctx: NodeContext, input_data: Any, config: dict[str, Any]
        ) -> NodeResult:
            return NodeResult(
                status="failed",
                output=None,
                logs=[],
                duration_ms=1,
                error=NodeError(
                    type="missing_credential", message="No credential named 'anthropic'"
                ),
            )

    err = fails(ClaudeNode(Failing()), {}, {"prompt": "hi"})
    assert err.type == "missing_credential"


async def test_a_real_workflow_through_the_engine_without_any_code_node(tmp_path: Path) -> None:
    """CSV text -> rows -> filter -> HTML report -> file on disk -> read back."""
    from app.domain.workflow import WorkflowDefinition
    from app.engine.executor import execute_workflow

    reg = default_registry(SubprocessRunner(), files_dir=tmp_path)
    nodes = [
        {"id": "parse", "type": "data.csv", "config": {"mode": "parse", "path": "$.csv"}},
        {
            "id": "keep",
            "type": "data.filter",
            "config": {
                "items_path": "$.rows",
                "where": [{"path": "$.score", "op": "eq", "value": "9"}],
            },
        },
        {
            "id": "page",
            "type": "text.template",
            "config": {
                "template": "<ul>{{ $.items }}</ul><p>{{ $.kept }} kept</p>",
                "escape_html": True,
            },
        },
        {
            "id": "save",
            "type": "file.write",
            "config": {"path": "report/out.html", "content_path": "$.text"},
        },
        {"id": "back", "type": "file.read", "config": {"path": "report/out.html"}},
    ]
    edges = [("parse", "keep"), ("keep", "page"), ("page", "save"), ("save", "back")]
    w = WorkflowDefinition.model_validate(
        {
            "nodes": nodes,
            "edges": [
                {"source": {"node": a}, "target": {"node": b, "port": "in"}} for a, b in edges
            ],
        }
    )
    run = await execute_workflow(w, reg, {"csv": "name,score\nann,9\nbob,5\ncy,9\n"})
    assert run.status == "succeeded", [(n.node_id, n.status, n.error) for n in run.nodes]
    html_text = (tmp_path / "report" / "out.html").read_text()
    assert (
        "<p>2 kept</p>" in html_text and "&quot;ann&quot;" in html_text and "bob" not in html_text
    )
    assert run.nodes[-1].output["text"] == html_text
