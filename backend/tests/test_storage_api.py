from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient

from app.main import create_app
from app.storage.db import make_engine, upgrade_to_head
from app.storage.models import Base

DOUBLE = "def main(i):\n    return {'v': i['v'] * 2}"
BOOM = "def main(i):\n    raise ValueError('boom')"


def defn(*sources: str, moved: int = 0) -> dict:  # type: ignore[type-arg]
    nodes = [
        {"id": f"n{i}", "type": "code.python", "config": {"source": s}}
        for i, s in enumerate(sources)
    ]
    edges = [
        {"source": {"node": f"n{i}"}, "target": {"node": f"n{i + 1}", "port": "in"}}
        for i in range(len(nodes) - 1)
    ]
    return {"nodes": nodes, "edges": edges, "ui": {"positions": {"n0": {"x": moved, "y": 0}}}}


def create(client: TestClient, d: dict) -> dict:  # type: ignore[type-arg]
    r = client.post("/api/v1/workflows", json={"name": "WF", "definition": d})
    assert r.status_code == 201
    return r.json()


def test_crud_and_optimistic_concurrency(client: TestClient) -> None:
    wf = create(client, defn(DOUBLE))
    assert wf["revision"] == 1 and wf["id"].startswith("wf_")
    body = {"name": "Renamed", "definition": defn(DOUBLE, DOUBLE), "revision": 1}
    r = client.put(f"/api/v1/workflows/{wf['id']}", json=body)
    assert r.status_code == 200 and r.json()["revision"] == 2
    stale = client.put(f"/api/v1/workflows/{wf['id']}", json=body)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "revision_conflict"
    assert [w["name"] for w in client.get("/api/v1/workflows").json()] == ["Renamed"]
    assert client.delete(f"/api/v1/workflows/{wf['id']}").status_code == 204
    assert client.get(f"/api/v1/workflows/{wf['id']}").status_code == 404


def test_versions_dedupe_and_ignore_layout(client: TestClient) -> None:
    wf = create(client, defn(DOUBLE))
    wid = wf["id"]
    v1 = client.post(f"/api/v1/workflows/{wid}/versions").json()
    again = client.post(f"/api/v1/workflows/{wid}/versions").json()
    assert v1["version_no"] == 1 and again["version_no"] == 1
    client.put(
        f"/api/v1/workflows/{wid}",
        json={"name": "WF", "definition": defn(DOUBLE, moved=500), "revision": 1},
    )
    assert (
        client.post(f"/api/v1/workflows/{wid}/versions").json()["version_no"] == 1
    )  # moved a node only
    client.put(
        f"/api/v1/workflows/{wid}", json={"name": "WF", "definition": defn(BOOM), "revision": 2}
    )
    assert client.post(f"/api/v1/workflows/{wid}/versions").json()["version_no"] == 2
    assert [v["version_no"] for v in client.get(f"/api/v1/workflows/{wid}/versions").json()] == [
        2,
        1,
    ]
    old = client.get(f"/api/v1/workflows/{wid}/versions/1").json()
    assert old["definition"]["nodes"][0]["config"]["source"] == DOUBLE  # snapshots are immutable


def test_run_is_pinned_persisted_and_listed(client: TestClient) -> None:
    wf = create(client, defn(DOUBLE, DOUBLE))
    wid = wf["id"]
    run = client.post(f"/api/v1/workflows/{wid}/runs", json={"input": {"v": 2}})
    assert run.status_code == 201
    data = run.json()
    assert data["status"] == "succeeded" and data["version_no"] == 1
    assert [n["output"] for n in data["nodes"]] == [{"v": 4}, {"v": 8}]
    # edit the draft afterwards; the old run still references version 1
    client.put(
        f"/api/v1/workflows/{wid}", json={"name": "WF", "definition": defn(BOOM), "revision": 1}
    )
    run2 = client.post(f"/api/v1/workflows/{wid}/runs", json={"input": {"v": 1}}).json()
    assert run2["status"] == "failed" and run2["version_no"] == 2
    assert [n["status"] for n in run2["nodes"]] == ["failed"]
    pinned = client.post(
        f"/api/v1/workflows/{wid}/runs", json={"version": 1, "input": {"v": 5}}
    ).json()
    assert pinned["status"] == "succeeded" and pinned["nodes"][-1]["output"] == {"v": 20}
    history = client.get(f"/api/v1/workflows/{wid}/runs").json()
    assert len(history) == 3 and history[0]["id"] == pinned["id"]
    fetched = client.get(f"/api/v1/runs/{run2['id']}").json()
    assert fetched["nodes"][0]["error"]["type"] == "runtime_error"
    assert fetched["input"] == {"v": 1}


def test_invalid_workflow_run_is_422(client: TestClient) -> None:
    wf = create(client, {"nodes": [{"id": "a", "type": "nope"}]})
    r = client.post(f"/api/v1/workflows/{wf['id']}/runs", json={})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_failed"
    assert client.post("/api/v1/workflows/missing/runs", json={}).status_code == 404


def test_data_survives_restart(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'p.db'}"
    with TestClient(create_app(url)) as c:
        wid = create(c, defn(DOUBLE))["id"]
    with TestClient(create_app(url)) as c:
        assert c.get(f"/api/v1/workflows/{wid}").status_code == 200


def test_migrations_match_models(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'm.db'}"
    upgrade_to_head(url)
    upgrade_to_head(url)  # idempotent
    with make_engine(url).connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_creates_missing_data_directory(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'does' / 'not' / 'exist' / 'n.db'}"
    with TestClient(create_app(url)) as c:
        assert c.get("/api/v1/workflows").json() == []
