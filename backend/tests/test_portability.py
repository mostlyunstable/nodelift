import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.errors import AppError
from app.config import Settings
from app.domain.migrations import migrate_definition
from app.domain.workflow import WorkflowDefinition
from app.main import create_app
from tests.test_run_events import start_run
from tests.test_storage_api import DOUBLE, create, defn, wait_run

CODE = {"id": "a", "type": "code.python", "name": "A", "config": {"source": DOUBLE}}
HTTP = {
    "id": "h",
    "type": "http.request",
    "config": {"url": "https://api.example.com/v1/x?token=abc"},
}


def file_for(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]] | None = None, **wf: Any
) -> dict[str, Any]:
    return {
        "format": "nodecraft-workflow",
        "format_version": 1,
        "workflow": {
            "name": "Imported",
            "definition": {"nodes": nodes, "edges": edges or [], **wf},
        },
    }


# ---------------------------------------------------------------- export


def test_export_then_import_round_trips(client: TestClient) -> None:
    wid = create(client, defn(DOUBLE, DOUBLE))["id"]
    exported = client.get(f"/api/v1/workflows/{wid}/export").json()
    assert exported["format"] == "nodecraft-workflow" and exported["format_version"] == 1
    assert exported["exported_at"].endswith("Z")
    assert len(exported["workflow"]["definition"]["nodes"]) == 2
    imported = client.post("/api/v1/workflows/import", json=exported)
    assert imported.status_code == 201
    new = imported.json()
    assert new["id"] != wid  # always a NEW workflow
    assert new["draft"]["id"] == new["id"]
    assert [n["config"] for n in new["draft"]["nodes"]] == [
        n["config"] for n in exported["workflow"]["definition"]["nodes"]
    ]
    assert len(client.get("/api/v1/workflows").json()) == 2  # the original is untouched


def test_export_unknown_workflow_is_404(client: TestClient) -> None:
    assert client.get("/api/v1/workflows/nope/export").status_code == 404


def test_export_everything_for_backups(client: TestClient) -> None:
    create(client, defn(DOUBLE))
    create(client, defn(DOUBLE, DOUBLE))
    body = client.get("/api/v1/system/export").json()
    assert body["format"] == "nodecraft-backup" and len(body["workflows"]) == 2
    assert all(w["format"] == "nodecraft-workflow" for w in body["workflows"])
    assert "runs" not in json.dumps(body)  # history stays out of the file


# ---------------------------------------------------------------- preview


def test_preview_says_what_the_file_can_do_without_creating_anything(client: TestClient) -> None:
    r = client.post("/api/v1/workflows/import/preview", json=file_for([CODE, HTTP]))
    body = r.json()
    assert r.status_code == 200 and body["valid"] is True
    s = body["summary"]
    assert (
        s["nodes"] == 2
        and s["code_nodes"] == 1
        and s["node_types"] == {"code.python": 1, "http.request": 1}
    )
    assert s["http_hosts"] == [
        "api.example.com"
    ]  # host only: the query string (token=abc) is not shown
    assert any("code node" in w for w in s["warnings"]) and any(
        "api.example.com" in w for w in s["warnings"]
    )
    assert "abc" not in json.dumps(s)
    assert client.get("/api/v1/workflows").json() == []  # nothing was created


def test_preview_reports_problems_instead_of_failing(client: TestClient) -> None:
    bad = file_for([{"id": "x", "type": "does.not.exist", "config": {}}])
    body = client.post("/api/v1/workflows/import/preview", json=bad).json()
    assert body["valid"] is False and body["issues"][0]["code"] == "unknown_node_type"


# ---------------------------------------------------------------- import safety


def test_import_refuses_invalid_workflows(client: TestClient) -> None:
    bad = file_for([{"id": "x", "type": "does.not.exist", "config": {}}])
    r = client.post("/api/v1/workflows/import", json=bad)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_failed"
    assert client.get("/api/v1/workflows").json() == []


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda f: f.update(format="something-else"), "not_a_workflow_file"),
        (lambda f: f.update(format_version=99), "unsupported_format_version"),
        (lambda f: f["workflow"].update(definition="not a dict"), "invalid_file"),
        (
            lambda f: f["workflow"]["definition"].update(schema_version=7),
            "unsupported_schema_version",
        ),
        (
            lambda f: f["workflow"]["definition"].update(surprise=1),
            "invalid_file",
        ),  # unknown fields are refused
        (lambda f: f["workflow"]["definition"]["nodes"][0].update(config="nope"), "invalid_file"),
    ],
)
def test_import_rejects_bad_files_with_a_specific_reason(
    client: TestClient, mutate: Any, code: str
) -> None:
    f = file_for([dict(CODE)])
    mutate(f)
    for path in ("/api/v1/workflows/import", "/api/v1/workflows/import/preview"):
        r = client.post(path, json=f)
        assert r.status_code == 422 and r.json()["error"]["code"] == code, (path, r.text)
    assert client.get("/api/v1/workflows").json() == []


def test_newer_format_message_tells_the_user_what_to_do(client: TestClient) -> None:
    f = file_for([dict(CODE)])
    f["format_version"] = 99
    msg = client.post("/api/v1/workflows/import", json=f).json()["error"]["message"]
    assert "newer Nodecraft" in msg and "Update" in msg


def test_import_keeps_only_sane_layout_and_never_trusts_ids(client: TestClient) -> None:
    f = file_for(
        [dict(CODE)],
        ui={
            "positions": {
                "a": {"x": 10, "y": 20},
                "b": {"x": "evil", "y": 1},
                "c": {"x": 1e999, "y": 1},
                "d": [1, 2],
            },
            "script": "<script>alert(1)</script>",
        },
        id="wf_someone_elses",
    )
    # raw JSON text, because a strict encoder refuses to write the Infinity this attack uses
    resp = client.post(
        "/api/v1/workflows/import",
        content=json.dumps(f, allow_nan=True),
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 201, resp.text
    new = resp.json()
    assert new["id"] != "wf_someone_elses"
    assert new["draft"]["ui"] == {"positions": {"a": {"x": 10.0, "y": 20.0}}}


def test_importing_never_runs_anything(tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    code = {
        "id": "a",
        "type": "code.python",
        "config": {"source": f"def main(i):\n    open({str(marker)!r}, 'w').write('x')"},
    }
    with TestClient(create_app(f"sqlite:///{tmp_path / 'i.db'}", Settings(data_dir=tmp_path))) as c:
        assert c.post("/api/v1/workflows/import/preview", json=file_for([code])).status_code == 200
        assert c.post("/api/v1/workflows/import", json=file_for([code])).status_code == 201
        assert c.get("/api/v1/workflows").json()[0]["revision"] == 1
        assert not marker.exists()  # reviewing and importing are not executing


def test_imported_workflow_runs_like_any_other(client: TestClient) -> None:
    wid = create(client, defn(DOUBLE, DOUBLE))["id"]
    new = client.post(
        "/api/v1/workflows/import", json=client.get(f"/api/v1/workflows/{wid}/export").json()
    ).json()
    run = wait_run(client, start_run(client, new["id"], input={"v": 3}))
    assert run["status"] == "succeeded" and run["nodes"][-1]["output"] == {"v": 12}


# ---------------------------------------------------------------- schema versions


def test_migrations_chain_in_order() -> None:
    steps = {
        1: lambda d: {**d, "name": d["name"] + "+1"},
        2: lambda d: {**d, "name": d["name"] + "+2"},
    }
    out = migrate_definition({"schema_version": 1, "name": "n"}, steps, current=3)
    assert out == {"schema_version": 3, "name": "n+1+2"}
    assert migrate_definition({"name": "n"}, steps, current=2)["name"] == "n+1"  # no version = v1


def test_newer_and_broken_versions_are_refused() -> None:
    with pytest.raises(AppError) as e:
        migrate_definition({"schema_version": 5}, {}, current=2)
    assert e.value.code == "unsupported_schema_version" and "Update Nodecraft" in e.value.message
    for bad in (0, -1, "2", True, None, 1.5):
        with pytest.raises(AppError) as err:
            migrate_definition({"schema_version": bad})
        assert err.value.code == "invalid_schema_version"
    with pytest.raises(AppError) as miss:
        migrate_definition({"schema_version": 1}, {}, current=2)
    assert miss.value.code == "missing_migration"


def test_migration_does_not_mutate_its_input() -> None:
    raw = {"schema_version": 1, "name": "n", "nodes": []}
    migrate_definition(raw, {1: lambda d: {**d, "x": 1}}, current=2)
    assert raw == {"schema_version": 1, "name": "n", "nodes": []}


def test_a_future_format_gives_a_readable_error_when_saving(client: TestClient) -> None:
    r = client.post("/api/v1/workflows", json={"name": "x", "definition": {"schema_version": 2}})
    assert r.status_code == 422
    assert "Update Nodecraft" in json.dumps(r.json())
    assert WorkflowDefinition().schema_version == 1


# ---------------------------------------------------------------- edge ports


def test_edges_must_use_real_ports(client: TestClient) -> None:
    nodes = [dict(CODE), {"id": "b", "type": "code.python", "config": {"source": DOUBLE}}]

    def issues(src_port: str, dst_port: str) -> list[str]:
        edge = {
            "source": {"node": "a", "port": src_port},
            "target": {"node": "b", "port": dst_port},
        }
        body = client.post(
            "/api/v1/workflows/validate", json={"nodes": nodes, "edges": [edge]}
        ).json()
        return [i["code"] for i in body["issues"]]

    assert issues("out", "in") == []
    assert issues("NOPE", "in") == ["unknown_port"]
    assert issues("out", "ALSO_NOPE") == ["unknown_port"]
    assert issues("in", "out") == ["unknown_port", "unknown_port"]  # direction matters


# ---------------------------------------------------------------- event paging and retention


def test_events_are_paged_and_say_when_more_remain(client: TestClient) -> None:
    wid = create(client, defn(DOUBLE, DOUBLE, DOUBLE))["id"]
    run_id = start_run(client, wid, input={"v": 1})
    wait_run(client, run_id)
    total = client.get(f"/api/v1/runs/{run_id}/events").json()
    assert len(total) == 8  # started + 3x(node.started, node.finished) + finished
    seen: list[int] = []
    after = 0
    pages = 0
    while True:
        r = client.get(f"/api/v1/runs/{run_id}/events", params={"after": after, "limit": 3})
        seen += [e["seq"] for e in r.json()]
        pages += 1
        if r.headers.get("x-has-more") != "1":
            break
        after = int(r.headers["x-next-after"])
    assert seen == [e["seq"] for e in total] and pages == 3  # nothing lost, nothing repeated
    assert client.get(f"/api/v1/runs/{run_id}/events", params={"limit": 0}).status_code == 422
    assert "x-has-more" not in client.get(f"/api/v1/runs/{run_id}/events").headers


def test_old_runs_are_pruned_but_the_newest_are_kept(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, keep_runs_per_workflow=2)
    with TestClient(create_app(f"sqlite:///{tmp_path / 'p.db'}", settings)) as c:
        wid = create(c, defn(DOUBLE))["id"]
        ids = []
        for _ in range(4):
            rid = start_run(c, wid, input={"v": 1})
            wait_run(c, rid)
            ids.append(rid)
        import time

        deadline = time.monotonic() + 3
        while (
            time.monotonic() < deadline and len(c.get(f"/api/v1/workflows/{wid}/runs").json()) > 2
        ):
            time.sleep(0.05)
        kept = [r["id"] for r in c.get(f"/api/v1/workflows/{wid}/runs").json()]
        assert sorted(kept) == sorted(ids[-2:])
        assert c.get(f"/api/v1/runs/{ids[0]}").status_code == 404
        assert c.get(f"/api/v1/runs/{ids[0]}/events").status_code == 404  # events went with it
