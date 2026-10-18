import asyncio
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.workflow import WorkflowDefinition, retry_policy, validate_workflow
from app.main import create_app
from app.nodes import default_registry
from app.runtime.subprocess_runner import SubprocessRunner
from tests.test_run_events import start_run
from tests.test_storage_api import BOOM, DOUBLE, create, wait_run

REG = default_registry(SubprocessRunner())
BACKEND = Path(__file__).resolve().parents[1]


def make_client(tmp_path: Path, **overrides: Any) -> Iterator[TestClient]:
    settings = Settings(data_dir=tmp_path, **overrides)
    with TestClient(create_app(f"sqlite:///{tmp_path / 'r.db'}", settings)) as c:
        yield c


def chain(*sources: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    nodes = [
        {"id": f"n{i}", "type": "code.python", "config": {"source": s, **(extra or {})}}
        for i, s in enumerate(sources)
    ]
    edges = [
        {"source": {"node": f"n{i}"}, "target": {"node": f"n{i + 1}", "port": "in"}}
        for i in range(len(nodes) - 1)
    ]
    return {"nodes": nodes, "edges": edges}


def sleeper(pidfile: Path, seconds: float) -> str:
    return (
        "import os, time\ndef main(i):\n"
        f"    open({str(pidfile)!r}, 'w').write(str(os.getpid()))\n"
        f"    time.sleep({seconds})\n    return {{'v': 1}}"
    )


def events(client: TestClient, run_id: str) -> list[dict[str, Any]]:
    return client.get(f"/api/v1/runs/{run_id}/events").json()  # type: ignore[no-any-return]


def wait_for_event(client: TestClient, run_id: str, type_: str, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(e["type"] == type_ for e in events(client, run_id)):
            return
        time.sleep(0.02)
    raise AssertionError(f"no {type_} event")


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def read_pid(path: Path, timeout: float = 8) -> int:
    """The node writes its own pid first, so tests can check the real worker process."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.read_text():
            return int(path.read_text())
        time.sleep(0.05)
    raise AssertionError("worker never reported its pid")


def wait_dead(pid: int, timeout: float = 8) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not alive(pid):
            return True
        time.sleep(0.1)
    return False


# ---------------------------------------------------------------- cancel


async def test_runner_cancel_kills_the_worker(tmp_path: Path) -> None:
    pidfile = tmp_path / "pid"
    cancel = asyncio.Event()
    task = asyncio.create_task(SubprocessRunner().run(sleeper(pidfile, 30), {}, 60, cancel))
    pid = await asyncio.to_thread(read_pid, pidfile)
    assert alive(pid)
    cancel.set()
    res = await asyncio.wait_for(task, 5)
    assert res.error and res.error.type == "cancelled"
    assert wait_dead(pid, 3)


def test_cancel_running_workflow(client: TestClient, tmp_path: Path) -> None:
    pidfile = tmp_path / "pid"
    wid = create(client, chain(sleeper(pidfile, 30), DOUBLE))["id"]
    run_id = start_run(client, wid, input={"v": 1})
    pid = read_pid(pidfile)
    r = client.post(f"/api/v1/runs/{run_id}/cancel")
    assert r.status_code == 202
    assert client.post(f"/api/v1/runs/{run_id}/cancel").status_code == 202  # idempotent
    run = wait_run(client, run_id)
    assert run["status"] == "cancelled"
    assert [(n["node_id"], n["status"]) for n in run["nodes"]] == [
        ("n0", "cancelled"),
        ("n1", "skipped"),
    ]
    types = [e["type"] for e in events(client, run_id)]
    assert types.count("run.cancel_requested") == 1 and types[-1] == "run.finished"
    assert events(client, run_id)[-1]["payload"] == {
        "status": "cancelled",
        "duration_ms": run["duration_ms"],
        "reason": "cancelled",
    }
    assert wait_dead(pid, 3)


def test_cancel_finished_or_unknown_run(client: TestClient) -> None:
    wid = create(client, chain(DOUBLE))["id"]
    run_id = start_run(client, wid, input={"v": 1})
    wait_run(client, run_id)
    r = client.post(f"/api/v1/runs/{run_id}/cancel")
    assert r.status_code == 202 and r.json()["status"] == "succeeded"
    assert client.post("/api/v1/runs/nope/cancel").status_code == 404


# ---------------------------------------------------------------- retries


def flaky(counter: Path, fail_times: int) -> str:
    return (
        "def main(i):\n"
        f"    p = {str(counter)!r}\n"
        "    try:\n        n = int(open(p).read())\n    except FileNotFoundError:\n        n = 0\n"
        "    open(p, 'w').write(str(n + 1))\n"
        f"    if n < {fail_times}:\n        raise RuntimeError('flaky')\n"
        "    return {'attempts': n + 1}\n"
    )


IDEMPOTENT_RETRY = {"idempotent": True, "retry": {"max_attempts": 3, "backoff_ms": 0}}


def test_idempotent_node_is_retried_until_it_succeeds(client: TestClient, tmp_path: Path) -> None:
    wf = chain(flaky(tmp_path / "c1", 2), extra=IDEMPOTENT_RETRY)
    wid = create(client, wf)["id"]
    run = wait_run(client, start_run(client, wid, input={}))
    assert run["status"] == "succeeded"
    assert [(n["attempt"], n["status"]) for n in run["nodes"]] == [
        (1, "failed"),
        (2, "failed"),
        (3, "succeeded"),
    ]
    finished = [e["payload"] for e in events(client, run["id"]) if e["type"] == "node.finished"]
    assert [f["will_retry"] for f in finished] == [True, True, False]


def test_retries_are_bounded_and_deterministic_errors_are_not_retried(
    client: TestClient, tmp_path: Path
) -> None:
    always = chain(flaky(tmp_path / "c2", 99), extra=IDEMPOTENT_RETRY)
    run = wait_run(client, start_run(client, create(client, always)["id"], input={}))
    assert run["status"] == "failed" and [n["attempt"] for n in run["nodes"]] == [1, 2, 3]
    syntax = chain("def main(:", extra=IDEMPOTENT_RETRY)
    run = wait_run(client, start_run(client, create(client, syntax)["id"], input={}))
    assert len(run["nodes"]) == 1 and run["nodes"][0]["error"]["type"] == "syntax_error"


def test_retry_requires_idempotent_flag(client: TestClient) -> None:
    wf = chain(BOOM, extra={"retry": {"max_attempts": 3}})
    wid = create(client, wf)["id"]
    r = client.post(f"/api/v1/workflows/{wid}/runs", json={})
    assert r.status_code == 422
    assert r.json()["error"]["details"][0]["code"] == "retry_requires_idempotent"


def test_retry_validation_and_policy() -> None:
    def wfd(config: dict[str, Any]) -> WorkflowDefinition:
        return WorkflowDefinition.model_validate(
            {"nodes": [{"id": "a", "type": "code.python", "config": {"source": "x", **config}}]}
        )

    assert validate_workflow(wfd({"idempotent": True, "retry": {"max_attempts": 2}}), REG) == []
    bad = validate_workflow(wfd({"idempotent": True, "retry": {"max_attempts": 99}}), REG)
    assert [i.code for i in bad] == ["invalid_config"]
    assert [i.code for i in validate_workflow(wfd({"idempotent": "yes"}), REG)] == [
        "invalid_config"
    ]
    node = wfd({"retry": {"max_attempts": 3}}).nodes[0]
    assert retry_policy(node) == (1, 0)  # not idempotent: never retried
    assert retry_policy(wfd(IDEMPOTENT_RETRY).nodes[0]) == (3, 0)


# ---------------------------------------------------------------- limits


@pytest.fixture
def tight_run_client(tmp_path: Path) -> Iterator[TestClient]:
    yield from make_client(tmp_path, max_run_seconds=1)


def test_run_wall_clock_budget(tight_run_client: TestClient, tmp_path: Path) -> None:
    c = tight_run_client
    wid = create(c, chain(*[sleeper(tmp_path / f"p{i}", 0.7) for i in range(3)]))["id"]
    run = wait_run(c, start_run(c, wid, input={}), timeout=15)
    assert run["status"] == "failed"
    assert [n["status"] for n in run["nodes"]][-1] == "skipped"
    assert events(c, run["id"])[-1]["payload"]["reason"] == "run_timeout"


@pytest.fixture
def one_run_client(tmp_path: Path) -> Iterator[TestClient]:
    yield from make_client(tmp_path, max_concurrent_runs=1)


def test_concurrent_run_limit(one_run_client: TestClient, tmp_path: Path) -> None:
    c = one_run_client
    wid = create(c, chain(sleeper(tmp_path / "pid", 30)))["id"]
    first = start_run(c, wid, input={})
    blocked = c.post(f"/api/v1/workflows/{wid}/runs", json={})
    assert blocked.status_code == 429 and blocked.json()["error"]["code"] == "too_many_runs"
    c.post(f"/api/v1/runs/{first}/cancel")
    wait_run(c, first)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:  # slot frees once the run task finishes
        if c.post(f"/api/v1/workflows/{wid}/runs", json={}).status_code == 202:
            break
        time.sleep(0.05)
    else:
        raise AssertionError("slot never freed")


async def test_file_size_limit() -> None:
    runner = SubprocessRunner(max_file_mb=1)
    src = "def main(i):\n    open('big.bin', 'wb').write(b'x' * (8 << 20))\n    return 1"
    res = await runner.run(src, None, 10)
    assert res.status == "failed"  # killed by SIGXFSZ or OSError


@pytest.mark.skipif(sys.platform != "linux", reason="RLIMIT_AS is only enforced on Linux")
async def test_memory_limit_linux() -> None:
    res = await SubprocessRunner(memory_mb=256).run(
        "def main(i):\n    return len(bytearray(1 << 30))", None, 10
    )
    assert res.status == "failed"


# ---------------------------------------------------------------- resume / crash recovery


def test_resume_reuses_succeeded_nodes(client: TestClient, tmp_path: Path) -> None:
    log, gate = tmp_path / "a.log", tmp_path / "gate"
    a = f"def main(i):\n    open({str(log)!r}, 'a').write('x')\n    return {{'v': i['v'] + 1}}"
    b = (
        "import os\ndef main(i):\n"
        f"    if not os.path.exists({str(gate)!r}):\n        raise RuntimeError('not yet')\n"
        "    return {'v': i['v'] * 10}"
    )
    wid = create(client, chain(a, b, DOUBLE))["id"]
    first = wait_run(client, start_run(client, wid, input={"v": 1}))
    assert first["status"] == "failed"
    assert [n["status"] for n in first["nodes"]] == ["succeeded", "failed", "skipped"]

    gate.write_text("open")
    r = client.post(f"/api/v1/runs/{first['id']}/resume")
    assert r.status_code == 202
    resumed = wait_run(client, r.json()["id"])
    assert resumed["status"] == "succeeded" and resumed["id"] != first["id"]
    assert [(n["node_id"], n["reused"]) for n in resumed["nodes"]] == [
        ("n0", True),
        ("n1", False),
        ("n2", False),
    ]
    assert resumed["nodes"][-1]["output"] == {"v": 40}
    assert log.read_text() == "x"  # node a ran exactly once across both runs
    started = events(client, resumed["id"])[0]["payload"]
    assert started["resumed_from"] == first["id"] and started["reused_nodes"] == ["n0"]

    assert client.post(f"/api/v1/runs/{resumed['id']}/resume").status_code == 409
    assert client.post("/api/v1/runs/nope/resume").status_code == 404


def test_crashed_run_is_closed_on_restart_and_can_be_resumed(tmp_path: Path) -> None:
    from app.domain.run import NodeExecution
    from app.storage.db import make_engine, make_session_factory, upgrade_to_head
    from app.storage.repositories import SqlRunRepository, SqlWorkflowRepository

    url = f"sqlite:///{tmp_path / 'crash.db'}"
    upgrade_to_head(url)
    sf = make_session_factory(make_engine(url))
    wfs = SqlWorkflowRepository(sf)
    definition = WorkflowDefinition.model_validate(chain(DOUBLE, DOUBLE))
    wf = wfs.create("w", definition)
    ver = wfs.add_version(wf.id, definition, "h")
    runs = SqlRunRepository(sf)
    runs.create("run_crashed", wf.id, ver, {"v": 3})
    runs.add_event("run_crashed", "run.started", {})
    # n0 finished and was persisted before the server died; n1 was in flight
    runs.add_node_execution(
        "run_crashed", 0, NodeExecution(node_id="n0", status="succeeded", output={"v": 6})
    )
    with TestClient(create_app(url, Settings(data_dir=tmp_path))) as c:
        assert c.get("/api/v1/runs/run_crashed").json()["status"] == "failed"
        resumed = wait_run(c, c.post("/api/v1/runs/run_crashed/resume").json()["id"])
    assert resumed["status"] == "succeeded"
    assert [n["reused"] for n in resumed["nodes"]] == [True, False]
    assert resumed["nodes"][1]["output"] == {"v": 12}  # n1 consumed the persisted n0 output


def test_worker_exits_when_the_server_is_killed(tmp_path: Path) -> None:
    pidfile = tmp_path / "pid"
    script = (
        "import asyncio\nfrom app.runtime.subprocess_runner import SubprocessRunner\n"
        f"src = {sleeper(pidfile, 60)!r}\n"
        "asyncio.run(SubprocessRunner().run(src, None, 120))\n"
    )
    parent = subprocess.Popen([sys.executable, "-c", script], cwd=BACKEND)
    worker = 0
    try:
        worker = read_pid(pidfile)
        assert alive(worker) and worker != parent.pid
        parent.kill()  # SIGKILL: the server gets no chance to clean up
        parent.wait()
        assert wait_dead(worker, 8), "worker outlived its parent"
    finally:
        if worker and alive(worker):
            os.kill(worker, 9)
        parent.kill()
