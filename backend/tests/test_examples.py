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


# ---------------------------------------------------------------- resume uses the CURRENT workflow


def edit_node(client: TestClient, wid: str, node_id: str, **config: Any) -> None:
    rec = client.get(f"/api/v1/workflows/{wid}").json()
    draft = rec["draft"]
    next(n for n in draft["nodes"] if n["id"] == node_id)["config"].update(config)
    r = client.put(
        f"/api/v1/workflows/{wid}",
        json={"name": rec["name"], "definition": draft, "revision": rec["revision"]},
    )
    assert r.status_code == 200


FIXED = (
    "def main(input_data):\n"
    '    items = input_data["items"]\n'
    '    return {"average": sum(items) / len(items)}\n'
)


def resume(client: TestClient, run_id: str) -> dict[str, Any]:
    r = client.post(f"/api/v1/runs/{run_id}/resume")
    assert r.status_code == 202, r.text
    return wait_run(client, r.json()["id"])


def test_fix_then_resume_runs_only_what_changed(client: TestClient) -> None:
    """The tutorial's promise: fix the bug, resume, and the finished steps are not run again."""
    wf = make(client)
    first = wait_run(client, start_run(client, wf["id"], input={}))
    assert first["status"] == "failed" and first["version_no"] == 1
    edit_node(client, wf["id"], "average", source=FIXED)
    resumed = resume(client, first["id"])
    assert resumed["status"] == "succeeded"
    assert resumed["version_no"] == 2  # it ran the fixed workflow, as a new pinned version
    reused = {n["node_id"]: n["reused"] for n in resumed["nodes"]}
    assert reused == {"make_data": True, "pick_fields": True, "average": False, "report": False}
    assert resumed["nodes"][-1]["output"] == {"average": 18.0, "note": "all done"}
    # the earlier run still describes what actually happened then
    assert client.get(f"/api/v1/runs/{first['id']}").json()["version_no"] == 1


def test_resume_without_changes_reuses_the_same_nodes_and_the_same_version(
    client: TestClient,
) -> None:
    wf = make(client)
    first = wait_run(client, start_run(client, wf["id"], input={}))
    again = resume(client, first["id"])
    assert again["version_no"] == 1  # nothing changed, so no new version
    assert [n["node_id"] for n in again["nodes"] if n["reused"]] == ["make_data", "pick_fields"]


def test_changing_an_upstream_node_reruns_everything_after_it(client: TestClient) -> None:
    wf = make(client)
    first = wait_run(client, start_run(client, wf["id"], input={}))
    # make_data changes, so pick_fields' input differs even though its own settings did not
    edit_node(
        client,
        wf["id"],
        "make_data",
        source='def main(input_data):\n    return {"items": [1, 2, 3], "count": 3}\n',
    )
    edit_node(client, wf["id"], "average", source=FIXED)
    resumed = resume(client, first["id"])
    assert [n["reused"] for n in resumed["nodes"]] == [False, False, False, False]
    assert resumed["status"] == "succeeded"
    assert (
        resumed["nodes"][-1]["output"]["average"] == 2.0
    )  # computed from the NEW data, not stale results


def test_changing_only_a_downstream_node_keeps_upstream_results(client: TestClient) -> None:
    wf = make(client)
    first = wait_run(client, start_run(client, wf["id"], input={}))
    edit_node(
        client, wf["id"], "report", mapping={"avg": "$.average"}
    )  # a different node, after the bug
    resumed = resume(client, first["id"])
    assert [n["node_id"] for n in resumed["nodes"] if n["reused"]] == ["make_data", "pick_fields"]
    assert resumed["status"] == "failed"  # the bug in `average` is still there


def test_a_node_whose_settings_changed_is_never_reused_even_with_identical_input(
    client: TestClient,
) -> None:
    wf = make(client)
    first = wait_run(client, start_run(client, wf["id"], input={}))
    edit_node(
        client,
        wf["id"],
        "pick_fields",
        mapping={"items": "$.items", "count": "$.count", "extra": {"literal": 1}},
    )
    edit_node(client, wf["id"], "average", source=FIXED)
    resumed = resume(client, first["id"])
    by = {n["node_id"]: n for n in resumed["nodes"]}
    assert by["make_data"]["reused"] is True  # untouched and same input
    assert by["pick_fields"]["reused"] is False  # its settings changed
    assert by["pick_fields"]["output"]["extra"] == 1  # the new setting really took effect
