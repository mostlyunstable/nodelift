import json
import time

from fastapi.testclient import TestClient

from app.main import create_app
from tests.test_storage_api import BOOM, DOUBLE, create, defn, wait_run

SLOW = "import time\ndef main(i):\n    time.sleep(0.3)\n    return {'v': i['v']}"


def parse_sse(text: str) -> list[dict]:  # type: ignore[type-arg]
    out = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "id" in fields:
            out.append(
                {"id": int(fields["id"]), "event": fields["event"], **json.loads(fields["data"])}
            )
    return out


def start_run(client: TestClient, wid: str, **body) -> str:  # type: ignore[no-untyped-def]
    r = client.post(f"/api/v1/workflows/{wid}/runs", json=body)
    assert r.status_code == 202
    return r.json()["id"]  # type: ignore[no-any-return]


def test_events_are_persisted_in_order(client: TestClient) -> None:
    wid = create(client, defn(DOUBLE, DOUBLE))["id"]
    run_id = start_run(client, wid, input={"v": 1})
    wait_run(client, run_id)
    events = client.get(f"/api/v1/runs/{run_id}/events").json()
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert [e["type"] for e in events] == [
        "run.started",
        "node.started",
        "node.finished",
        "node.started",
        "node.finished",
        "run.finished",
    ]
    assert events[-1]["payload"]["status"] == "succeeded"


def test_catch_up_after_seq(client: TestClient) -> None:
    wid = create(client, defn(DOUBLE, DOUBLE))["id"]
    run_id = start_run(client, wid, input={"v": 1})
    wait_run(client, run_id)
    rest = client.get(f"/api/v1/runs/{run_id}/events", params={"after": 4}).json()
    assert [e["seq"] for e in rest] == [5, 6]


def test_sse_streams_live_and_closes_on_finish(client: TestClient) -> None:
    wid = create(client, defn(SLOW, DOUBLE))["id"]
    run_id = start_run(client, wid, input={"v": 1})
    with client.stream("GET", f"/api/v1/runs/{run_id}/events/stream") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())  # returns when the server closes the stream
    events = parse_sse(body)
    assert events[0]["event"] == "run.started" and events[-1]["event"] == "run.finished"
    assert [e["id"] for e in events] == list(range(1, len(events) + 1))
    first_finish = next(e for e in events if e["event"] == "node.finished")
    assert first_finish["node_id"] == "n0" and first_finish["duration_ms"] >= 300


def test_sse_resumes_from_last_event_id(client: TestClient) -> None:
    wid = create(client, defn(DOUBLE, BOOM))["id"]
    run_id = start_run(client, wid, input={"v": 1})
    wait_run(client, run_id)
    with client.stream(
        "GET", f"/api/v1/runs/{run_id}/events/stream", headers={"Last-Event-ID": "3"}
    ) as r:
        events = parse_sse("".join(r.iter_text()))
    assert [e["id"] for e in events] == [4, 5, 6]
    assert events[-1]["status"] == "failed"
    assert events[-2]["error_type"] == "runtime_error"


def test_skipped_nodes_emit_events(client: TestClient) -> None:
    wid = create(client, defn(BOOM, DOUBLE))["id"]
    run_id = start_run(client, wid, input={"v": 1})
    wait_run(client, run_id)
    events = client.get(f"/api/v1/runs/{run_id}/events").json()
    finished = [
        (e["payload"]["node_id"], e["payload"]["status"])
        for e in events
        if e["type"] == "node.finished"
    ]
    assert finished == [("n0", "failed"), ("n1", "skipped")]


def test_partial_run_is_visible_while_running(client: TestClient) -> None:
    wid = create(client, defn(DOUBLE, SLOW))["id"]
    run_id = start_run(client, wid, input={"v": 1})
    deadline = time.monotonic() + 5
    seen = None
    while time.monotonic() < deadline:
        seen = client.get(f"/api/v1/runs/{run_id}").json()
        if seen["status"] == "running" and len(seen["nodes"]) == 1:
            break
        time.sleep(0.02)
    assert seen and seen["status"] == "running" and len(seen["nodes"]) == 1
    assert wait_run(client, run_id)["status"] == "succeeded"


def test_unknown_run_is_404(client: TestClient) -> None:
    assert client.get("/api/v1/runs/nope/events").status_code == 404
    assert client.get("/api/v1/runs/nope/events/stream").status_code == 404


def test_stale_running_runs_are_closed_on_startup(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from app.domain.workflow import WorkflowDefinition
    from app.storage.db import make_engine, make_session_factory, upgrade_to_head
    from app.storage.repositories import SqlRunRepository, SqlWorkflowRepository

    url = f"sqlite:///{tmp_path / 'r.db'}"
    upgrade_to_head(url)
    sf = make_session_factory(make_engine(url))
    wf = SqlWorkflowRepository(sf).create("w", WorkflowDefinition())
    ver = SqlWorkflowRepository(sf).add_version(wf.id, WorkflowDefinition(), "h")
    runs = SqlRunRepository(sf)
    runs.create("run_orphan", wf.id, ver, None)  # simulates a crash mid-run
    runs.add_event("run_orphan", "run.started", {})
    with TestClient(create_app(url)) as c:
        assert c.get("/api/v1/runs/run_orphan").json()["status"] == "failed"
        events = c.get("/api/v1/runs/run_orphan/events").json()
        assert events[-1]["type"] == "run.finished"
        assert events[-1]["payload"]["reason"] == "server_restarted"
        with c.stream("GET", "/api/v1/runs/run_orphan/events/stream") as r:
            assert parse_sse("".join(r.iter_text()))[-1]["event"] == "run.finished"
