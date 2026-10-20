import json
import logging
import sys
import threading
import types
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.ports import CodeRunResult, LogLine, NodeError
from app.domain.secrets import (
    MASK,
    MemorySecretStore,
    MissingCredential,
    Redactor,
    SecretResolver,
    SecretsUnavailable,
    references,
)
from app.main import create_app
from app.storage.secret_stores import KeyringSecretStore
from tests.test_run_events import start_run
from tests.test_storage_api import create, wait_run

CANARY = "canary-Sup3r-S3cret/value+1=="  # has characters that change under URL / JSON encoding


# ---------------------------------------------------------- local server that echoes credentials


class Echo(BaseHTTPRequestHandler):
    seen: list[str] = []

    def log_message(self, *args: Any) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        auth = self.headers.get("Authorization", "")
        Echo.seen.append(auth)
        if self.path.startswith("/deny"):
            body, status = f"forbidden for {auth}".encode(), 403
        else:
            body, status = json.dumps({"you_sent": auth, "path": self.path}).encode(), 200
        self.send_response(status)
        self.send_header("Content-Type", "application/json" if status == 200 else "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def echo() -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Echo)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(autouse=True)
def reset_seen() -> None:
    Echo.seen = []


@pytest.fixture
def app_client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(data_dir=tmp_path, http_allow_private=True, secret_backend="memory")
    with TestClient(create_app(f"sqlite:///{tmp_path / 'c.db'}", settings)) as c:
        c.db_path = tmp_path / "c.db"  # type: ignore[attr-defined]
        yield c


def add_credential(c: TestClient, name: str = "canary", value: str = CANARY) -> None:
    r = c.post("/api/v1/credentials", json={"name": name, "value": value})
    assert r.status_code == 201, r.text


# ---------------------------------------------------------------- redaction primitives


def test_redactor_masks_the_value_and_its_encoded_forms() -> None:
    r = Redactor()
    r.register(CANARY)
    from urllib.parse import quote

    assert r.text(f"Bearer {CANARY}") == f"Bearer {MASK}"
    assert r.text(f"?token={quote(CANARY, safe='')}") == f"?token={MASK}"
    assert (
        json.loads(r.text(json.dumps({"k": CANARY})))["k"] == MASK
    )  # the JSON-escaped form is masked
    assert r.text("nothing secret here") == "nothing secret here"


def test_redactor_walks_nested_data_including_keys() -> None:
    r = Redactor()
    r.register(CANARY)
    out = r.data({"a": [CANARY, {"b": f"x{CANARY}y"}], CANARY: 1, "n": 5, "ok": True, "none": None})
    assert CANARY not in json.dumps(out)
    assert (
        out["a"][0] == MASK
        and out["a"][1]["b"] == f"x{MASK}y"
        and out["n"] == 5
        and out["none"] is None
    )


def test_redactor_ignores_values_too_short_to_mask_safely() -> None:
    r = Redactor()
    r.register("short")
    assert not r.active and r.text("a short story") == "a short story"


def test_redactor_cleans_a_whole_node_result() -> None:
    r = Redactor()
    r.register(CANARY)
    res = CodeRunResult(
        status="failed",
        output={"echo": CANARY},
        logs=[LogLine(stream="stdout", text=f"sent {CANARY}")],
        duration_ms=1,
        error=NodeError(type="http_error", message=f"403 {CANARY}", traceback=f"line {CANARY}"),
    )
    clean = r.result(res)
    assert CANARY not in clean.model_dump_json()
    assert (
        clean.logs[0].text == f"sent {MASK}"
        and clean.error
        and clean.error.message == f"403 {MASK}"
    )
    assert res.output == {"echo": CANARY}  # the original object is not mutated
    plain = Redactor()
    assert plain.result(res) is res  # nothing to hide: untouched


def test_longest_form_is_masked_first() -> None:
    r = Redactor()
    r.register("abcdefgh")
    r.register("abcdefghijkl")
    assert r.text("x abcdefghijkl y") == f"x {MASK} y"


def test_resolver_substitutes_references_and_registers_them_for_masking() -> None:
    store = MemorySecretStore()
    store.set("one", "first-secret-value")
    store.set("two", "second-secret-value")
    redactor = Redactor()
    text = SecretResolver(store, redactor).resolve("a {{credential:one}} b {{credential:two}} c")
    assert text == "a first-secret-value b second-secret-value c"
    assert redactor.text(text) == f"a {MASK} b {MASK} c"
    with pytest.raises(MissingCredential):
        SecretResolver(store, Redactor()).resolve("{{credential:ghost}}")
    assert references(
        "{{credential:a}} {{credential:b-c.d}} {{ credential:x }} {{credential:bad name}}"
    ) == ["a", "b-c.d"]


class FakeKeyring(types.ModuleType):
    class errors:  # noqa: N801
        class PasswordDeleteError(Exception): ...

    def __init__(self) -> None:
        super().__init__("keyring")
        self.items: dict[tuple[str, str], str] = {}
        self.fail = False

    def get_password(self, service: str, name: str) -> str | None:
        if self.fail:
            raise RuntimeError("keychain locked")
        return self.items.get((service, name))

    def set_password(self, service: str, name: str, value: str) -> None:
        if self.fail:
            raise RuntimeError("keychain locked")
        self.items[(service, name)] = value

    def delete_password(self, service: str, name: str) -> None:
        if self.fail:
            raise RuntimeError("keychain locked")
        if (service, name) not in self.items:
            raise self.errors.PasswordDeleteError("missing")
        del self.items[(service, name)]


def test_keyring_store_uses_the_system_keychain_and_reports_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeKeyring()
    monkeypatch.setitem(sys.modules, "keyring", fake)
    monkeypatch.setitem(sys.modules, "keyring.errors", fake.errors)  # type: ignore[arg-type]
    store = KeyringSecretStore()
    store.set("gh", "token-value-123")
    assert fake.items == {("Nodecraft", "gh"): "token-value-123"}
    assert store.get("gh") == "token-value-123" and store.get("nope") is None
    store.delete("gh")
    store.delete("gh")  # deleting twice is fine
    fake.fail = True
    for action in (
        lambda: store.get("x"),
        lambda: store.set("x", "yyyyyyyy"),
        lambda: store.delete("x"),
    ):
        with pytest.raises(SecretsUnavailable, match="keychain locked"):
            action()


# ---------------------------------------------------------------- the credentials API


def test_credentials_are_write_only(app_client: TestClient) -> None:
    c = app_client
    r = c.post(
        "/api/v1/credentials",
        json={"name": "github", "value": CANARY, "kind": "token", "description": "ci"},
    )
    assert r.status_code == 201
    body = r.json()
    assert set(body) == {
        "id",
        "name",
        "kind",
        "description",
        "created_at",
        "updated_at",
    }  # no value, ever
    listing = c.get("/api/v1/credentials")
    assert [x["name"] for x in listing.json()] == ["github"]
    for response in (r, listing):
        assert CANARY not in response.text
    assert c.get("/api/v1/credentials/github").status_code in (
        404,
        405,
    )  # there is no way to read it back


def test_creating_validates_name_value_and_duplicates(app_client: TestClient) -> None:
    c = app_client

    def create_cred(**kw: Any) -> Any:
        return c.post("/api/v1/credentials", json={"name": "ok-name", "value": CANARY, **kw})

    assert create_cred(name="has space").status_code == 422
    assert create_cred(name="x" * 65).status_code == 422
    assert create_cred(name="../etc").status_code == 422
    assert create_cred(value="short").json()["error"]["code"] == "secret_too_short"
    assert create_cred(value="line\nbreak-in-secret").json()["error"]["code"] == "invalid_secret"
    assert create_cred().status_code == 201
    dup = create_cred()
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "credential_exists"
    assert "ok-name" in dup.text and CANARY not in dup.text


def test_rotate_and_delete(app_client: TestClient) -> None:
    c = app_client
    add_credential(c, "k", "first-secret-value")
    store: MemorySecretStore = c.app.state.secrets  # type: ignore[attr-defined]
    assert store.get("k") == "first-secret-value"
    r = c.put(
        "/api/v1/credentials/k", json={"value": "second-secret-value", "description": "rotated"}
    )
    assert r.status_code == 200 and r.json()["description"] == "rotated"
    assert store.get("k") == "second-secret-value"
    assert c.put("/api/v1/credentials/ghost", json={"value": "whatever-value-1"}).status_code == 404
    assert c.put("/api/v1/credentials/k", json={"value": "tiny"}).status_code == 422
    assert store.get("k") == "second-secret-value"  # a rejected rotation changes nothing
    assert c.delete("/api/v1/credentials/k").status_code == 204
    assert (
        store.get("k") is None and c.get("/api/v1/credentials").json() == []
    )  # gone from both places
    assert c.delete("/api/v1/credentials/k").status_code == 404


def test_a_locked_keychain_is_reported_and_nothing_half_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeKeyring()
    fake.fail = True
    monkeypatch.setitem(sys.modules, "keyring", fake)
    monkeypatch.setitem(sys.modules, "keyring.errors", fake.errors)  # type: ignore[arg-type]
    settings = Settings(data_dir=tmp_path, secret_backend="keyring")
    with TestClient(create_app(f"sqlite:///{tmp_path / 'k.db'}", settings)) as c:
        r = c.post("/api/v1/credentials", json={"name": "a", "value": CANARY})
        assert r.status_code == 503 and r.json()["error"]["code"] == "secrets_unavailable"
        assert c.get("/api/v1/credentials").json() == []  # no database row without a stored secret


def test_credential_routes_need_the_api_token(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, api_token="t" * 24, secret_backend="memory")
    with TestClient(create_app(f"sqlite:///{tmp_path / 't.db'}", settings)) as c:
        assert c.get("/api/v1/credentials").status_code == 401
        assert c.post("/api/v1/credentials", json={"name": "a", "value": CANARY}).status_code == 401


# ----------------------------------------------------------- using a credential, and not leaking it


def http_node(url: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": "call",
        "type": "http.request",
        "config": {
            "url": url,
            "headers": {"Authorization": "Bearer {{credential:canary}}"},
            **extra,
        },
    }


def everything_the_app_stored(c: TestClient) -> str:
    """Every byte on disk plus every API response that could carry node data."""
    db = c.db_path  # type: ignore[attr-defined]
    raw = b"".join(p.read_bytes() for p in db.parent.glob(db.name + "*") if p.is_file())
    return raw.decode("latin-1")


def test_the_real_value_is_sent_but_never_shown_or_stored(
    app_client: TestClient, echo: str, caplog: pytest.LogCaptureFixture
) -> None:
    c = app_client
    add_credential(c)
    caplog.set_level(logging.DEBUG)
    wid = create(c, {"nodes": [http_node(f"{echo}/whoami")]})["id"]
    run = wait_run(c, start_run(c, wid, input={}))
    assert run["status"] == "succeeded"
    assert Echo.seen == [f"Bearer {CANARY}"]  # the server really received the secret
    assert (
        run["nodes"][0]["output"]["body"]["you_sent"] == f"Bearer {MASK}"
    )  # ...but the echo was masked
    events = c.get(f"/api/v1/runs/{run['id']}/events").text
    full = c.get(f"/api/v1/runs/{run['id']}").text
    stored = (
        c.get(f"/api/v1/workflows/{wid}").text + c.get(f"/api/v1/workflows/{wid}/versions/1").text
    )
    for place, text in {
        "events": events,
        "run": full,
        "workflow": stored,
        "disk": everything_the_app_stored(c),
        "logs": caplog.text,
    }.items():
        assert CANARY not in text, f"secret leaked into {place}"
    assert "{{credential:canary}}" in stored  # the workflow holds the reference, not the value


def test_secrets_are_masked_in_error_messages_too(app_client: TestClient, echo: str) -> None:
    c = app_client
    add_credential(c)
    wid = create(c, {"nodes": [http_node(f"{echo}/deny")]})["id"]
    run = wait_run(c, start_run(c, wid, input={}))
    assert run["status"] == "failed"
    node = run["nodes"][0]
    assert node["error"]["type"] == "http_error" and f"Bearer {MASK}" in node["error"]["message"]
    assert Echo.seen == [f"Bearer {CANARY}"]
    assert CANARY not in c.get(f"/api/v1/runs/{run['id']}").text
    assert CANARY not in everything_the_app_stored(c)


def test_single_node_test_masks_secrets_as_well(app_client: TestClient, echo: str) -> None:
    c = app_client
    add_credential(c)
    node = http_node(f"{echo}/whoami")
    r = c.post("/api/v1/nodes/test", json={"type": "http.request", "config": node["config"]})
    assert r.status_code == 200 and r.json()["status"] == "succeeded"
    assert Echo.seen == [f"Bearer {CANARY}"] and CANARY not in r.text
    assert r.json()["output"]["body"]["you_sent"] == f"Bearer {MASK}"


def test_a_missing_credential_fails_clearly_and_is_not_retried(
    app_client: TestClient, echo: str
) -> None:
    c = app_client
    node = http_node(f"{echo}/whoami", idempotent=True, retry={"max_attempts": 3, "backoff_ms": 0})
    wid = create(c, {"nodes": [node]})["id"]
    run = wait_run(c, start_run(c, wid, input={}))
    assert run["status"] == "failed" and len(run["nodes"]) == 1  # never retried
    err = run["nodes"][0]["error"]
    assert (
        err["type"] == "missing_credential"
        and "'canary'" in err["message"]
        and "Credentials" in err["message"]
    )
    assert Echo.seen == []  # nothing was sent without the credential


def test_deleting_a_credential_stops_workflows_from_using_it(
    app_client: TestClient, echo: str
) -> None:
    c = app_client
    add_credential(c)
    wid = create(c, {"nodes": [http_node(f"{echo}/whoami")]})["id"]
    assert wait_run(c, start_run(c, wid, input={}))["status"] == "succeeded"
    c.delete("/api/v1/credentials/canary")
    again = wait_run(c, start_run(c, wid, input={}))
    assert (
        again["status"] == "failed" and again["nodes"][0]["error"]["type"] == "missing_credential"
    )


def test_credentials_are_checked_syntactically_when_a_workflow_is_validated(
    app_client: TestClient,
) -> None:
    def problems(config: dict[str, Any]) -> list[str]:
        body = {"nodes": [{"id": "n", "type": "http.request", "config": config}]}
        return [
            i["message"]
            for i in app_client.post("/api/v1/workflows/validate", json=body).json()["issues"]
        ]

    ok = {
        "url": "https://api.example.com",
        "headers": {"Authorization": "Bearer {{credential:github}}"},
    }
    assert problems(ok) == []
    assert any(
        "only be used in header values" in p
        for p in problems({"url": "https://x.example/?t={{credential:a}}"})
    )
    bad_header = {"url": "https://api.example.com", "headers": {"X": "{{credential:bad name}}"}}
    assert any("malformed credential reference" in p for p in problems(bad_header))


def test_exported_workflows_carry_the_reference_never_the_value(
    app_client: TestClient, echo: str
) -> None:
    c = app_client
    add_credential(c)
    wid = create(c, {"nodes": [http_node("https://api.example.com/v1")]})["id"]
    exported = c.get(f"/api/v1/workflows/{wid}/export")
    assert CANARY not in exported.text and "{{credential:canary}}" in exported.text
    assert CANARY not in c.get("/api/v1/system/export").text
    preview = c.post("/api/v1/workflows/import/preview", json=exported.json()).json()
    assert preview["summary"]["credentials"] == ["canary"]
    assert any("Needs credentials: canary" in w for w in preview["summary"]["warnings"])
