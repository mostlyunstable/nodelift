import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.domain.nodes import NodeContext
from app.domain.run import ExecutionRun
from app.domain.workflow import WorkflowDefinition, validate_workflow
from app.engine.executor import execute_workflow
from app.nodes import default_registry
from app.nodes.builtin.branch import BranchNode, evaluate
from app.nodes.builtin.json_transform import _MISSING
from app.runtime.subprocess_runner import SubprocessRunner
from tests.test_run_events import start_run
from tests.test_storage_api import create, wait_run

REG = default_registry(SubprocessRunner())
MARK = "def main(i):\n    return {'seen': i}"


def branch(path: str = "$.n", op: str = "gt", value: Any = 10, **extra: Any) -> dict[str, Any]:
    return {"path": path, "operator": op, "value": value, **extra}


def workflow(
    nodes: dict[str, tuple[str, dict[str, Any]]], edges: list[tuple[str, str, str]]
) -> WorkflowDefinition:
    """nodes: id -> (type, config); edges: (source, source_port, target)."""
    return WorkflowDefinition.model_validate(
        {
            "nodes": [{"id": i, "type": t, "config": c} for i, (t, c) in nodes.items()],
            "edges": [
                {"source": {"node": a, "port": p}, "target": {"node": b, "port": "in"}}
                for a, p, b in edges
            ],
        }
    )


def run(wf: WorkflowDefinition, value: Any, **kw: Any) -> ExecutionRun:
    assert validate_workflow(wf, REG) == []
    return asyncio.run(execute_workflow(wf, REG, value, **kw))


def statuses(r: ExecutionRun) -> dict[str, str]:
    return {n.node_id: n.status for n in r.nodes}


# ---------------------------------------------------------------- the condition


@pytest.mark.parametrize(
    ("op", "found", "expected", "result"),
    [
        ("gt", 11, 10, True), ("gt", 10, 10, False), ("gte", 10, 10, True), ("lt", 9, 10, True),
        ("lte", 10, 10, True), ("gt", 2.5, 2, True),
        ("gt", "11", 10, False), ("gt", True, 0, False),  # only real numbers compare
        ("eq", 1, 1.0, True), ("eq", 1, True, False), ("eq", "1", 1, False), ("eq", "a", "a", True),
        ("eq", {"a": 1}, {"a": 1}, True), ("ne", "a", "b", True), ("ne", 1, True, True),
        ("truthy", 0, None, False), ("truthy", "x", None, True), ("truthy", [], None, False),
        ("truthy", None, None, False), ("exists", None, None, True),
        ("contains", "hello world", "world", True), ("contains", "hello", 5, False),
        ("contains", [1, 2, 3], 2, True), ("contains", [1, 2, 3], True, False),
        ("contains", {"k": 1}, "k", True), ("contains", 42, 4, False),
    ],
)  # fmt: skip
def test_operators(op: str, found: Any, expected: Any, result: bool) -> None:
    assert evaluate(op, found, expected) is result


def test_a_missing_value_is_no_unless_you_ask_whether_it_exists() -> None:
    for op in ("truthy", "eq", "ne", "gt", "contains"):
        assert evaluate(op, _MISSING, 1) is False
    assert evaluate("exists", _MISSING, None) is False


async def test_the_node_passes_its_input_through_on_the_chosen_port() -> None:
    node = BranchNode()
    yes = await node.execute(NodeContext(5), {"n": 50, "keep": "me"}, branch())
    no = await node.execute(NodeContext(5), {"n": 3}, branch())
    assert yes.output == {"n": 50, "keep": "me"} and yes.activated_ports == ["true"]
    assert no.activated_ports == ["false"]
    missing = await node.execute(NodeContext(5), {"x": 1}, branch())
    assert missing.status == "succeeded" and missing.activated_ports == ["false"]
    strict = await node.execute(NodeContext(5), {"x": 1}, branch(strict=True))
    assert strict.status == "failed" and strict.error and strict.error.type == "transform_error"


@pytest.mark.parametrize(
    ("config", "needle"),
    [
        ({}, "config.path"),
        ({"path": "n", "operator": "truthy"}, "must start with $"),
        ({"path": "$.n", "operator": "bigger"}, "operator must be one of"),
        ({"path": "$.n", "operator": "gt"}, "needs config.value"),
        ({"path": "$.n", "operator": "truthy", "strict": "yes"}, "strict"),
    ],
)
def test_config_validation(config: dict[str, Any], needle: str) -> None:
    problems = BranchNode().validate_config(config)
    assert problems and needle in problems[0]


def test_valid_configs() -> None:
    assert BranchNode().validate_config({"path": "$", "operator": "truthy"}) == []
    assert BranchNode().validate_config(branch()) == []
    assert BranchNode().validate_config({"path": "$.a", "operator": "exists"}) == []


# ---------------------------------------------------------------- routing through the engine


def diamond() -> WorkflowDefinition:
    return workflow(
        {
            "check": ("logic.branch", branch()),
            "big": ("code.python", {"source": MARK}),
            "small": ("code.python", {"source": MARK}),
            "after_big": ("code.python", {"source": MARK}),
        },
        [("check", "true", "big"), ("check", "false", "small"), ("big", "out", "after_big")],
    )


def test_only_the_taken_branch_runs_and_everything_after_it() -> None:
    r = run(diamond(), {"n": 50})
    assert statuses(r) == {
        "check": "succeeded",
        "big": "succeeded",
        "small": "skipped",
        "after_big": "succeeded",
    }
    skipped = next(n for n in r.nodes if n.node_id == "small")
    assert skipped.skip_reason == "branch_not_taken"
    assert next(n for n in r.nodes if n.node_id == "big").output == {
        "seen": {"n": 50}
    }  # got the input
    assert r.status == "succeeded"  # an untaken branch is not a failure


def test_the_other_branch_runs_when_the_condition_is_false() -> None:
    r = run(diamond(), {"n": 1})
    assert statuses(r) == {
        "check": "succeeded",
        "big": "skipped",
        "small": "succeeded",
        "after_big": "skipped",
    }
    assert next(n for n in r.nodes if n.node_id == "after_big").skip_reason == "branch_not_taken"
    assert r.status == "succeeded"


def test_branches_can_merge_and_the_merge_runs_with_whichever_side_fired() -> None:
    wf = workflow(
        {
            "check": ("logic.branch", branch()),
            "a": ("code.python", {"source": "def main(i):\n    return 'from a'"}),
            "b": ("code.python", {"source": "def main(i):\n    return 'from b'"}),
            "merge": ("code.python", {"source": MARK}),
        },
        [
            ("check", "true", "a"),
            ("check", "false", "b"),
            ("a", "out", "merge"),
            ("b", "out", "merge"),
        ],
    )
    hi, lo = run(wf, {"n": 99}), run(wf, {"n": 0})
    assert next(n for n in hi.nodes if n.node_id == "merge").output == {"seen": {"a": "from a"}}
    assert next(n for n in lo.nodes if n.node_id == "merge").output == {"seen": {"b": "from b"}}
    assert (
        hi.status == lo.status == "succeeded"
    )  # same input SHAPE either way: an object keyed by node id


def test_both_ports_into_the_same_node_runs_it_once_with_the_value() -> None:
    wf = workflow(
        {"check": ("logic.branch", branch()), "t": ("code.python", {"source": MARK})},
        [("check", "true", "t"), ("check", "false", "t")],
    )
    r = run(wf, {"n": 1})
    assert [n.node_id for n in r.nodes].count("t") == 1 and statuses(r)["t"] == "succeeded"


def test_branches_chain() -> None:
    wf = workflow(
        {
            "big": ("logic.branch", branch("$.n", "gt", 10)),
            "huge": ("logic.branch", branch("$.n", "gt", 100)),
            "tiny": ("code.python", {"source": MARK}),
            "medium": ("code.python", {"source": MARK}),
            "enormous": ("code.python", {"source": MARK}),
        },
        [
            ("big", "false", "tiny"),
            ("big", "true", "huge"),
            ("huge", "false", "medium"),
            ("huge", "true", "enormous"),
        ],
    )
    assert statuses(run(wf, {"n": 5}))["tiny"] == "succeeded"
    mid = statuses(run(wf, {"n": 50}))
    assert mid["medium"] == "succeeded" and mid["tiny"] == mid["enormous"] == "skipped"
    assert statuses(run(wf, {"n": 500}))["enormous"] == "succeeded"


def test_a_failure_still_stops_everything_downstream_even_across_a_branch() -> None:
    wf = workflow(
        {
            "boom": ("code.python", {"source": "def main(i):\n    raise ValueError('x')"}),
            "check": ("logic.branch", branch()),
            "after": ("code.python", {"source": MARK}),
        },
        [("boom", "out", "check"), ("check", "true", "after")],
    )
    r = run(wf, {"n": 50})
    assert statuses(r) == {"boom": "failed", "check": "skipped", "after": "skipped"}
    assert next(n for n in r.nodes if n.node_id == "check").skip_reason == "upstream_failed"
    assert r.status == "failed"


def test_a_merge_after_a_branch_and_a_failed_sibling_does_not_run() -> None:
    wf = workflow(
        {
            "check": ("logic.branch", branch()),
            "ok": ("code.python", {"source": MARK}),
            "boom": ("code.python", {"source": "def main(i):\n    raise ValueError('x')"}),
            "merge": ("code.python", {"source": MARK}),
        },
        [
            ("check", "true", "ok"),
            ("check", "true", "boom"),
            ("ok", "out", "merge"),
            ("boom", "out", "merge"),
        ],
    )
    r = run(wf, {"n": 50})
    assert statuses(r)["merge"] == "skipped"
    assert next(n for n in r.nodes if n.node_id == "merge").skip_reason == "upstream_failed"


def test_a_strict_branch_failure_stops_the_run() -> None:
    wf = workflow(
        {
            "check": ("logic.branch", branch(strict=True)),
            "after": ("code.python", {"source": MARK}),
        },
        [("check", "true", "after")],
    )
    r = run(wf, {"no": "n"})
    assert statuses(r) == {"check": "failed", "after": "skipped"}


def test_a_workflow_that_starts_with_a_branch_works() -> None:
    wf = workflow(
        {
            "check": ("logic.branch", branch("$", "truthy", None)),
            "t": ("code.python", {"source": MARK}),
        },
        [("check", "true", "t")],
    )
    assert statuses(run(wf, "yes"))["t"] == "succeeded"
    assert statuses(run(wf, ""))["t"] == "skipped"


# ---------------------------------------------------------------- validation of ports


def test_branch_ports_are_true_and_false_only() -> None:
    def issues(port: str) -> list[str]:
        wf = workflow(
            {"c": ("logic.branch", branch()), "t": ("code.python", {"source": MARK})},
            [("c", port, "t")],
        )
        return [i.code for i in validate_workflow(wf, REG)]

    assert issues("true") == [] and issues("false") == []
    assert issues("out") == ["unknown_port"]  # a branch has no generic output
    assert issues("maybe") == ["unknown_port"]


# ---------------------------------------------------------------- persistence, resume and the API


def stored_diamond() -> dict[str, Any]:
    d = diamond()
    return {
        "nodes": [n.model_dump() for n in d.nodes],
        "edges": [e.model_dump() for e in d.edges],
    }


def test_runs_remember_which_branch_fired_and_why_nodes_were_skipped(client: TestClient) -> None:
    wid = create(client, stored_diamond())["id"]
    run_id = start_run(client, wid, input={"n": 50})
    wait_run(client, run_id)
    fetched = client.get(f"/api/v1/runs/{run_id}").json()  # reloaded from the database
    by = {n["node_id"]: n for n in fetched["nodes"]}
    assert by["check"]["activated_ports"] == ["true"]
    assert by["small"]["status"] == "skipped" and by["small"]["skip_reason"] == "branch_not_taken"
    events = client.get(f"/api/v1/runs/{run_id}/events").json()
    skipped = [e["payload"] for e in events if e["payload"].get("skip_reason")]
    assert [e["node_id"] for e in skipped] == ["small"]


def test_resume_keeps_the_branch_decision_of_a_reused_branch_node(client: TestClient) -> None:
    nodes = stored_diamond()
    nodes["nodes"] = [
        n
        if n["id"] != "after_big"
        else {**n, "config": {"source": "def main(i):\n    raise ValueError('x')"}}
        for n in nodes["nodes"]
    ]
    wid = create(client, nodes)["id"]
    first = wait_run(client, start_run(client, wid, input={"n": 50}))
    assert first["status"] == "failed"
    r = client.post(f"/api/v1/runs/{first['id']}/resume")
    resumed = wait_run(client, r.json()["id"])
    by = {n["node_id"]: n for n in resumed["nodes"]}
    assert by["check"]["reused"] is True and by["check"]["activated_ports"] == [
        "true"
    ]  # decision restored
    assert by["big"]["reused"] is True
    assert (
        by["small"]["status"] == "skipped"
    )  # still the untaken side: the reused branch fired `true`


def test_the_branch_node_is_in_the_palette(client: TestClient) -> None:
    defs = {d["type"]: d for d in client.get("/api/v1/nodes/definitions").json()}
    assert [p["name"] for p in defs["logic.branch"]["outputs"]] == ["true", "false"]
    r = client.post(
        "/api/v1/nodes/test",
        json={"type": "logic.branch", "config": branch(), "input": {"n": 99}},
    )
    assert r.status_code == 200 and r.json()["activated_ports"] == ["true"]
