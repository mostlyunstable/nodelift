import asyncio
import json
import socket
import sys
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpcore
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.nodes import NodeContext, NodeRegistry
from app.main import create_app
from app.nodes import default_registry, load_plugins
from app.nodes.builtin.http_request import HttpRequestNode
from app.nodes.builtin.json_transform import JsonTransformNode, parse_path
from app.runtime.net_guard import BlockedAddress, GuardedBackend, check_ip
from app.runtime.subprocess_runner import SubprocessRunner
from tests.test_reliability import events
from tests.test_run_events import start_run
from tests.test_storage_api import create, wait_run

# ------------------------------------------------------------------ local HTTP server


class Handler(BaseHTTPRequestHandler):
    hits: list[dict[str, Any]] = []

    def log_message(self, *args: Any) -> None:
        pass

    def _serve(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length).decode() if length else ""
        Handler.hits.append(
            {"method": self.command, "path": self.path, "headers": dict(self.headers), "body": body}
        )
        route = self.path.split("?")[0]
        if route == "/json":
            self._send(200, json.dumps({"hello": "world", "n": 1}), "application/json")
        elif route == "/echo":
            echo = {"method": self.command, "body": body, "x": self.headers.get("X-Test")}
            self._send(200, json.dumps(echo), "application/json")
        elif route == "/missing":
            self._send(404, "nope", "text/plain")
        elif route == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif route == "/big":
            self._send(200, "x" * 200_000, "text/plain")
        elif route == "/slow":
            time.sleep(2)
            self._send(200, "late", "text/plain")
        else:
            self._send(200, "plain text", "text/plain")

    def _send(self, status: int, body: str, ctype: str) -> None:
        raw = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    do_GET = do_POST = do_PUT = do_DELETE = _serve  # noqa: N815


@pytest.fixture(scope="module")
def server() -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(autouse=True)
def reset_hits() -> None:
    Handler.hits = []


def ctx(timeout: float = 5, cancel: asyncio.Event | None = None) -> NodeContext:
    return NodeContext(timeout, cancel)


LOCAL = HttpRequestNode(allow_private=True)  # tests talk to 127.0.0.1
STRICT = HttpRequestNode()  # production behaviour

# ------------------------------------------------------------------ json transform


async def run_transform(data: Any, mapping: dict[str, Any], **extra: Any) -> Any:
    return await JsonTransformNode().execute(ctx(), data, {"mapping": mapping, **extra})


async def test_transform_paths_and_literals() -> None:
    data = {
        "user": {"name": "Ada", "tags": ["a", "b"], "my-key": 1},
        "items": [{"id": 7}, {"id": 9}],
    }
    res = await run_transform(
        data,
        {
            "name": "$.user.name",
            "last_tag": "$.user.tags[-1]",
            "second_id": "$.items[1].id",
            "dash": '$["user"]["my-key"]',
            "whole": "$.user.tags",
            "const": {"literal": {"a": [1]}},
            "missing": "$.user.nothing",
            "oob": "$.items[5]",
        },
    )
    assert res.status == "succeeded"
    assert res.output == {
        "name": "Ada", "last_tag": "b", "second_id": 9, "dash": 1, "whole": ["a", "b"],
        "const": {"a": [1]}, "missing": None, "oob": None,
    }  # fmt: skip


async def test_transform_strict_fails_on_missing_path() -> None:
    res = await run_transform({"a": 1}, {"x": "$.b"}, strict=True)
    assert res.status == "failed" and res.error and res.error.type == "transform_error"
    assert "$.b" in res.error.message


@pytest.mark.parametrize(
    ("config", "needle"),
    [
        ({}, "non-empty object"),
        ({"mapping": {}}, "non-empty object"),
        ({"mapping": {"a": "user.name"}}, "must start with $"),
        ({"mapping": {"a": "$.a b"}}, "unexpected character"),
        ({"mapping": {"a": 5}}, "path string or"),
        ({"mapping": {"a": {"literal": 1, "x": 2}}}, "path string or"),
        ({"mapping": {"a": "$"}, "strict": "yes"}, "strict"),
    ],
)
def test_transform_validation(config: dict[str, Any], needle: str) -> None:
    problems = JsonTransformNode().validate_config(config)
    assert problems and needle in problems[0]


def test_parse_path() -> None:
    assert parse_path("$") == []
    assert parse_path('$.a[0]["b c"]') == ["a", 0, "b c"]


# ------------------------------------------------------------------ registry and plugins


def test_registry_rejects_duplicates_and_lists_definitions() -> None:
    reg = default_registry(SubprocessRunner())
    assert [d.type for d in reg.definitions()] == [
        "code.python",
        "transform.json",
        "logic.branch",
        "http.request",
    ]
    assert reg.get("nope") is None
    with pytest.raises(ValueError, match="already registered"):
        reg.register(JsonTransformNode())


def write_plugin(tmp_path: Path, name: str, body: str) -> None:
    (tmp_path / f"{name}.py").write_text(body)
    if str(tmp_path) not in sys.path:
        sys.path.insert(0, str(tmp_path))


PLUGIN = """
from app.domain.nodes import NodeDefinition, NodeResult

class Upper:
    definition = NodeDefinition(type="demo.upper", title="Upper", category="Demo")
    def validate_config(self, config):
        return []
    async def execute(self, ctx, input_data, config):
        out = {"text": input_data["text"].upper()}
        return NodeResult(status="succeeded", output=out, duration_ms=0)

def register(registry):
    registry.register(Upper())
"""


def test_load_plugins(tmp_path: Path) -> None:
    write_plugin(tmp_path, "nc_plugin_ok", PLUGIN)
    write_plugin(tmp_path, "nc_plugin_bad", "x = 1\n")
    reg = NodeRegistry()
    load_plugins(reg, ["nc_plugin_ok"])
    assert reg.get("demo.upper") is not None
    with pytest.raises(RuntimeError, match="no register"):
        load_plugins(reg, ["nc_plugin_bad"])
    with pytest.raises(ModuleNotFoundError):
        load_plugins(reg, ["nc_plugin_missing"])


def test_plugin_node_runs_in_a_workflow(tmp_path: Path) -> None:
    write_plugin(tmp_path, "nc_plugin_wf", PLUGIN)
    settings = Settings(data_dir=tmp_path, node_plugins="nc_plugin_wf")
    with TestClient(create_app(f"sqlite:///{tmp_path / 'p.db'}", settings)) as c:
        types = [d["type"] for d in c.get("/api/v1/nodes/definitions").json()]
        assert "demo.upper" in types
        wf = {"nodes": [{"id": "a", "type": "demo.upper", "config": {}}]}
        run = wait_run(c, start_run(c, create(c, wf)["id"], input={"text": "hi"}))
        assert run["status"] == "succeeded" and run["nodes"][0]["output"] == {"text": "HI"}


# ------------------------------------------------------------------ SSRF guard


@pytest.mark.parametrize(
    "addr",
    [
        "127.0.0.1", "127.8.9.1", "10.0.0.1", "172.16.5.4", "192.168.1.1", "169.254.169.254",
        "0.0.0.0", "100.64.0.1", "224.0.0.1", "255.255.255.255", "::1", "::", "fe80::1", "fc00::1",
        "::ffff:127.0.0.1", "::ffff:10.0.0.1", "::ffff:169.254.169.254", "64:ff9b::7f00:1",
        "2002:7f00:1::1", "fe80::1%en0",
    ],
)  # fmt: skip
def test_private_addresses_are_blocked(addr: str) -> None:
    with pytest.raises(BlockedAddress):
        check_ip(addr)


@pytest.mark.parametrize("addr", ["8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700:4700::1111"])
def test_public_addresses_are_allowed(addr: str) -> None:
    check_ip(addr)


async def test_one_private_dns_answer_poisons_the_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = GuardedBackend()

    async def fake_getaddrinfo(host: str, port: int, **kw: Any) -> list[Any]:
        return [
            (socket.AF_INET, 1, 6, "", ("93.184.216.34", port)),
            (socket.AF_INET, 1, 6, "", ("10.0.0.5", port)),
        ]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(BlockedAddress):
        await backend.connect_tcp("rebind.example", 80)


async def test_connection_goes_to_the_validated_address(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = GuardedBackend()
    seen: list[str] = []

    async def fake_getaddrinfo(host: str, port: int, **kw: Any) -> list[Any]:
        return [(socket.AF_INET, 1, 6, "", ("93.184.216.34", port))]

    async def fake_connect(host: str, port: int, *a: Any, **kw: Any) -> Any:
        seen.append(host)
        raise httpcore.ConnectError("stop")

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(backend._inner, "connect_tcp", fake_connect)
    with pytest.raises(httpcore.ConnectError):
        await backend.connect_tcp("example.com", 443)
    assert seen == ["93.184.216.34"]  # the checked IP, never the hostname (no second lookup)


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "localhost",
        "[::1]",
        "169.254.169.254",
        "2130706433",
        "0x7f.0.0.1",
        "[::ffff:7f00:1]",
    ],
)
async def test_http_node_blocks_internal_hosts(server: str, host: str) -> None:
    port = server.rsplit(":", 1)[1]
    res = await STRICT.execute(ctx(), None, {"url": f"http://{host}:{port}/json"})
    assert res.status == "failed" and res.error
    assert res.error.type in {"blocked_request", "network_error"}  # never a response
    assert Handler.hits == []  # nothing reached the local server


# ------------------------------------------------------------------ HTTP node behaviour


async def test_http_get_json(server: str) -> None:
    res = await LOCAL.execute(ctx(), None, {"url": f"{server}/json?token=SECRET"})
    assert res.status == "succeeded"
    assert res.output["status"] == 200 and res.output["ok"] is True
    assert res.output["body"] == {"hello": "world", "n": 1}
    assert res.output["headers"]["content-type"] == "application/json"
    assert "SECRET" not in json.dumps([x.model_dump() for x in res.logs])  # query never logged
    assert res.logs[0].text.endswith("/json -> 200")


async def test_http_post_body_headers_and_input_body(server: str) -> None:
    cfg = {
        "url": f"{server}/echo",
        "method": "POST",
        "headers": {"X-Test": "yes"},
        "body": {"a": 1},
    }
    res = await LOCAL.execute(ctx(), None, cfg)
    assert res.output["body"] == {"method": "POST", "body": '{"a": 1}', "x": "yes"}
    assert Handler.hits[0]["headers"]["Content-Type"] == "application/json"
    res = await LOCAL.execute(
        ctx(),
        {"from": "input"},
        {"url": f"{server}/echo", "method": "PUT", "send_input_as_body": True},
    )
    assert json.loads(res.output["body"]["body"]) == {"from": "input"}


async def test_http_error_status(server: str) -> None:
    res = await LOCAL.execute(ctx(), None, {"url": f"{server}/missing"})
    assert res.status == "failed" and res.error and res.error.type == "http_error"
    assert "404" in res.error.message
    res = await LOCAL.execute(
        ctx(), None, {"url": f"{server}/missing", "fail_on_error_status": False}
    )
    assert res.status == "succeeded" and res.output["status"] == 404 and res.output["ok"] is False


async def test_http_redirects_are_not_followed(server: str) -> None:
    res = await LOCAL.execute(ctx(), None, {"url": f"{server}/redirect"})
    assert res.status == "succeeded" and res.output["status"] == 302
    assert res.output["headers"]["location"].startswith("http://169.254.169.254")
    assert [h["path"] for h in Handler.hits] == [
        "/redirect"
    ]  # the metadata URL was never requested


async def test_http_response_size_cap(server: str) -> None:
    res = await LOCAL.execute(ctx(), None, {"url": f"{server}/big", "max_response_kb": 64})
    assert res.error and res.error.type == "response_too_large"
    ok = await LOCAL.execute(ctx(), None, {"url": f"{server}/big", "max_response_kb": 256})
    assert ok.status == "succeeded" and len(ok.output["body"]) == 200_000


async def test_http_timeout_and_cancel(server: str) -> None:
    res = await LOCAL.execute(ctx(), None, {"url": f"{server}/slow", "timeout_s": 0.3})
    assert res.error and res.error.type == "timeout"
    cancel = asyncio.Event()
    task = asyncio.create_task(
        LOCAL.execute(ctx(10, cancel), None, {"url": f"{server}/slow", "timeout_s": 10})
    )
    await asyncio.sleep(0.3)
    cancel.set()
    res = await asyncio.wait_for(task, 3)
    assert res.error and res.error.type == "cancelled"


async def test_http_connection_refused_is_a_network_error() -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]  # closed again on exit, so nothing listens here
    res = await LOCAL.execute(ctx(), None, {"url": f"http://127.0.0.1:{port}/"})
    assert res.error and res.error.type == "network_error"


@pytest.mark.parametrize(
    ("config", "needle"),
    [
        ({}, "url must be a string"),
        ({"url": "file:///etc/passwd"}, "absolute http(s) URL"),
        ({"url": "ftp://example.com/x"}, "absolute http(s) URL"),
        ({"url": "http://"}, "absolute http(s) URL"),
        ({"url": "http://user:pw@example.com"}, "credentials"),
        ({"url": "https://example.com", "method": "TRACE"}, "method"),
        ({"url": "https://example.com", "headers": {"Host": "evil"}}, "cannot be set"),
        ({"url": "https://example.com", "headers": {"X": "a\r\nInjected: 1"}}, "invalid header"),
        ({"url": "https://example.com", "headers": {"Bad Name": "x"}}, "invalid header"),
        ({"url": "https://example.com", "timeout_s": 999}, "timeout_s"),
        ({"url": "https://example.com", "max_response_kb": 10**9}, "max_response_kb"),
        ({"url": "https://example.com", "fail_on_error_status": "no"}, "fail_on_error_status"),
    ],
)
def test_http_config_validation(config: dict[str, Any], needle: str) -> None:
    problems = HttpRequestNode().validate_config(config)
    assert any(needle in p for p in problems), problems


def test_http_valid_config() -> None:
    cfg = {"url": "https://api.example.com/v1?x=1", "method": "POST", "headers": {"Accept": "a/b"}}
    assert HttpRequestNode().validate_config(cfg) == []


# ------------------------------------------------------------------ through the API


def test_definitions_endpoint(client: TestClient) -> None:
    defs = {d["type"]: d for d in client.get("/api/v1/nodes/definitions").json()}
    assert set(defs) == {"code.python", "transform.json", "logic.branch", "http.request"}
    assert defs["http.request"]["config_schema"]["required"] == ["url"]
    assert defs["transform.json"]["default_config"]["mapping"] == {"value": "$"}


def test_generic_node_test_endpoint(client: TestClient) -> None:
    body = {"type": "transform.json", "config": {"mapping": {"n": "$.a"}}, "input": {"a": 5}}
    r = client.post("/api/v1/nodes/test", json=body)
    assert r.status_code == 200 and r.json()["output"] == {"n": 5}
    assert client.post("/api/v1/nodes/test", json={"type": "nope"}).status_code == 422
    bad = client.post("/api/v1/nodes/test", json={"type": "transform.json", "config": {}})
    assert bad.status_code == 422 and bad.json()["error"]["details"][0]["code"] == "invalid_config"


def test_default_deployment_blocks_http_to_localhost(client: TestClient, server: str) -> None:
    r = client.post(
        "/api/v1/nodes/test", json={"type": "http.request", "config": {"url": f"{server}/json"}}
    )
    assert r.status_code == 200
    assert r.json()["error"]["type"] == "blocked_request" and Handler.hits == []


CALC = "def main(i):\n    return {'n2': i['n'] * 2}"


def test_pipeline_http_transform_code(tmp_path: Path, server: str) -> None:
    settings = Settings(data_dir=tmp_path, http_allow_private=True)
    wf = {
        "nodes": [
            {"id": "get", "type": "http.request", "config": {"url": f"{server}/json"}},
            {"id": "pick", "type": "transform.json", "config": {"mapping": {"n": "$.body.n"}}},
            {"id": "calc", "type": "code.python", "config": {"source": CALC}},
        ],
        "edges": [
            {"source": {"node": "get"}, "target": {"node": "pick", "port": "in"}},
            {"source": {"node": "pick"}, "target": {"node": "calc", "port": "in"}},
        ],
    }  # fmt: skip
    with TestClient(create_app(f"sqlite:///{tmp_path / 'w.db'}", settings)) as c:
        run = wait_run(c, start_run(c, create(c, wf)["id"], input={}))
        assert run["status"] == "succeeded", run
        assert run["nodes"][-1]["output"] == {"n2": 2}


def test_http_failure_is_retried_only_when_idempotent(tmp_path: Path, server: str) -> None:
    settings = Settings(data_dir=tmp_path, http_allow_private=True)
    cfg = {
        "url": f"{server}/missing",
        "idempotent": True,
        "retry": {"max_attempts": 2, "backoff_ms": 0},
    }
    wf = {"nodes": [{"id": "a", "type": "http.request", "config": cfg}]}
    with TestClient(create_app(f"sqlite:///{tmp_path / 'r.db'}", settings)) as c:
        run = wait_run(c, start_run(c, create(c, wf)["id"], input={}))
        assert run["status"] == "failed" and [n["attempt"] for n in run["nodes"]] == [1, 2]
        finished = [e for e in events(c, run["id"]) if e["type"] == "node.finished"]
        assert [e["payload"]["error_type"] for e in finished] == ["http_error", "http_error"]


def test_blocked_request_is_never_retried(tmp_path: Path, server: str) -> None:
    cfg = {
        "url": f"{server}/json",
        "idempotent": True,
        "retry": {"max_attempts": 3, "backoff_ms": 0},
    }
    wf = {"nodes": [{"id": "a", "type": "http.request", "config": cfg}]}
    settings = Settings(data_dir=tmp_path)  # private addresses NOT allowed
    with TestClient(create_app(f"sqlite:///{tmp_path / 'b.db'}", settings)) as c:
        run = wait_run(c, start_run(c, create(c, wf)["id"], input={}))
        assert run["status"] == "failed" and len(run["nodes"]) == 1
        assert run["nodes"][0]["error"]["type"] == "blocked_request"
    assert Handler.hits == []
