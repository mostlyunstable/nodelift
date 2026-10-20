import json
import time
from typing import Any

from fastapi.testclient import TestClient

from app.examples import load_examples
from tests.test_run_events import start_run
from tests.test_storage_api import wait_run


def make(client: TestClient) -> dict[str, Any]:
    r = client.post("/api/v1/examples/debug-me/create")
    assert r.status_code == 201
    return r.json()  # type: ignore[no-any-return]


def test_every_shipped_example_is_valid(client: TestClient) -> None:
    examples = load_examples()
    assert "debug-me" in examples
    for example_id, example in examples.items():
        body = client.post("/api/v1/workflows/validate", json=example["definition"]).json()
        assert body == {"valid": True, "issues": []}, example_id
        assert client.post(f"/api/v1/examples/{example_id}/create").status_code == 201


def test_examples_are_listed_and_unknown_ones_404(client: TestClient) -> None:
    listing = client.get("/api/v1/examples").json()
    assert [e["id"] for e in listing] == ["debug-me"] and listing[0]["nodes"] == 4
    assert client.post("/api/v1/examples/nope/create").status_code == 404


def test_each_create_makes_a_separate_workflow(client: TestClient) -> None:
    a, b = make(client), make(client)
    assert a["id"] != b["id"] and a["name"] == "Debug me (example)"
    assert len(client.get("/api/v1/workflows").json()) == 2


def test_the_tutorial_really_fails_where_it_says_and_resume_fixes_it(client: TestClient) -> None:
    """The first-run experience is only honest if this is true."""
    wf = make(client)
    run = wait_run(client, start_run(client, wf["id"], input={}))
    assert run["status"] == "failed"
    by_node = {n["node_id"]: n for n in run["nodes"]}
    assert (
        by_node["make_data"]["status"] == "succeeded"
        and by_node["pick_fields"]["status"] == "succeeded"
    )
    failed = by_node["average"]
    assert failed["status"] == "failed" and failed["error"]["type"] == "runtime_error"
    assert "ZeroDivisionError" in failed["error"]["message"]
    assert (
        'File "<node>", line 5' in failed["error"]["traceback"]
    )  # the line the tutorial points at
    assert failed["input"] == {
        "items": [4, 8, 15, 16, 23, 42],
        "count": 0,
    }  # the input that caused it
    assert by_node["report"]["status"] == "skipped"

    # the fix the example's comment suggests
    draft = client.get(f"/api/v1/workflows/{wf['id']}").json()
    nodes = draft["draft"]["nodes"]
    average = next(n for n in nodes if n["id"] == "average")
    average["config"]["source"] = (
        "def main(input_data):\n"
        '    items = input_data["items"]\n'
        '    return {"average": sum(items) / len(items)}\n'
    )
    saved = client.put(
        f"/api/v1/workflows/{wf['id']}",
        json={"name": draft["name"], "definition": draft["draft"], "revision": draft["revision"]},
    )
    assert saved.status_code == 200

    # resume reuses what already worked
    fresh = wait_run(client, start_run(client, wf["id"], input={}))  # new version, runs everything
    assert fresh["status"] == "succeeded"
    assert fresh["nodes"][-1]["output"] == {"average": 18.0, "note": "all done"}
    assert json.dumps(fresh)  # serialisable end to end


def test_resuming_the_failed_tutorial_run_skips_the_finished_nodes(client: TestClient) -> None:
    wf = make(client)
    first = wait_run(client, start_run(client, wf["id"], input={}))
    r = client.post(f"/api/v1/runs/{first['id']}/resume")
    assert r.status_code == 202
    time.sleep(0.05)
    resumed = wait_run(client, r.json()["id"])
    reused = [n["node_id"] for n in resumed["nodes"] if n["reused"]]
    assert reused == ["make_data", "pick_fields"]  # not run again
    assert resumed["status"] == "failed"  # same bug, same version: failing the same way is correct
