from app.domain.workflow import WorkflowDefinition, topological_order, validate_workflow
from app.engine.executor import execute_workflow
from app.nodes import default_registry
from app.runtime.subprocess_runner import SubprocessRunner

REG = default_registry(SubprocessRunner())


def wf(nodes: dict[str, str], edges: list[tuple[str, str]]) -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(
        {
            "nodes": [
                {"id": i, "type": "code.python", "config": {"source": s}} for i, s in nodes.items()
            ],
            "edges": [
                {"source": {"node": a}, "target": {"node": b, "port": "in"}} for a, b in edges
            ],
        }
    )


DOUBLE = "def main(i):\n    return {'v': i['v'] * 2}"
BOOM = "def main(i):\n    raise ValueError('boom')"


async def test_chain_passes_data() -> None:
    w = wf({"a": DOUBLE, "b": DOUBLE}, [("a", "b")])
    run = await execute_workflow(w, REG, {"v": 3})
    assert run.status == "succeeded"
    assert [n.output for n in run.nodes] == [{"v": 6}, {"v": 12}]
    assert run.nodes[1].input == {"v": 6}


async def test_failure_skips_downstream() -> None:
    w = wf({"a": BOOM, "b": DOUBLE, "c": DOUBLE}, [("a", "b"), ("b", "c")])
    run = await execute_workflow(w, REG, {"v": 1})
    assert run.status == "failed"
    assert [n.status for n in run.nodes] == ["failed", "skipped", "skipped"]
    assert run.nodes[0].error and run.nodes[0].error.type == "runtime_error"


async def test_fan_in_is_keyed_by_node_id() -> None:
    w = wf(
        {"a": DOUBLE, "b": DOUBLE, "c": "def main(i):\n    return sorted(i)"},
        [("a", "c"), ("b", "c")],
    )
    run = await execute_workflow(w, REG, {"v": 1})
    assert run.nodes[-1].output == ["a", "b"]


def test_cycle_and_dangling_detected() -> None:
    cyc = wf({"a": DOUBLE, "b": DOUBLE}, [("a", "b"), ("b", "a")])
    assert topological_order(cyc) is None
    assert [i.code for i in validate_workflow(cyc, REG)] == ["cycle"]
    dang = wf({"a": DOUBLE}, [("a", "zzz")])
    assert "dangling_edge" in [i.code for i in validate_workflow(dang, REG)]


def test_api_validate_and_legacy_run_removed(client) -> None:  # type: ignore[no-untyped-def]
    v = client.post("/api/v1/workflows/validate", json={"nodes": [{"id": "a", "type": "nope"}]})
    assert v.json()["valid"] is False
    ok = client.post(
        "/api/v1/workflows/validate",
        json={"nodes": [{"id": "a", "type": "code.python", "config": {"source": DOUBLE}}]},
    )
    assert ok.json() == {"valid": True, "issues": []}
    # the unmetered ad-hoc run endpoint no longer exists; runs go through the execution gate
    assert client.post("/api/v1/runs", json={"workflow": {}}).status_code in (404, 405)
