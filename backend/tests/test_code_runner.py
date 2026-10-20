import asyncio
import os

import pytest

from app.config import Settings
from app.runtime.subprocess_runner import SubprocessRunner

runner = SubprocessRunner()


async def run(src: str, inp: object = None, timeout: float = 5):
    return await runner.run(src, inp, timeout)


async def test_hello() -> None:
    r = await run('def main(input_data):\n    return {"message": "Hello from Nodecraft"}')
    assert r.status == "succeeded"
    assert r.output == {"message": "Hello from Nodecraft"}
    assert r.error is None


async def test_input_and_logs() -> None:
    r = await run("def main(i):\n    print('hi')\n    return {'t': sum(i['v'])}", {"v": [1, 2, 3]})
    assert r.output == {"t": 6}
    assert [(x.stream, x.text) for x in r.logs] == [("stdout", "hi")]


async def test_syntax_error() -> None:
    r = await run("def main(i)\n    return 1")
    assert r.status == "failed" and r.error
    assert r.error.type == "syntax_error" and r.error.line == 1


async def test_missing_main() -> None:
    r = await run("x = 1")
    assert r.error and r.error.type == "missing_main"


async def test_runtime_error_traceback_is_trimmed() -> None:
    r = await run("def main(i):\n    return 1/0")
    assert r.error and r.error.type == "runtime_error"
    assert "ZeroDivisionError" in r.error.message
    assert r.error.traceback and "worker_entry" not in r.error.traceback


@pytest.mark.parametrize("expr", ["{1, 2}", "float('nan')", "object()"])
async def test_invalid_output(expr: str) -> None:
    r = await run(f"def main(i):\n    return {expr}")
    assert r.error and r.error.type == "invalid_output"


async def test_timeout_kills_child(tmp_path) -> None:  # type: ignore[no-untyped-def]
    pidfile = tmp_path / "pid"
    src = (
        "import os\ndef main(i):\n"
        f"    open({str(pidfile)!r}, 'w').write(str(os.getpid()))\n    while True: pass"
    )
    # the pid file lives outside the worker's scratch folder, so use an unconfined runner here;
    # kill-on-timeout is the same code path with or without the sandbox (see test_sandbox.py)
    r = await SubprocessRunner(sandbox_mode="off").run(src, None, 0.8)
    assert r.error and r.error.type == "timeout"
    pid = int(pidfile.read_text())
    for _ in range(30):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        await asyncio.sleep(0.1)
    else:
        raise AssertionError("worker still alive after timeout")


async def test_output_too_large() -> None:
    r = await run("def main(i):\n    return 'x' * (6 * 1024 * 1024)", timeout=10)
    assert r.error and r.error.type == "output_too_large"


async def test_env_is_scrubbed() -> None:
    os.environ["NODECRAFT_TEST_SECRET"] = "s3cret"
    r = await run("import os\ndef main(i):\n    return dict(os.environ)")
    assert "NODECRAFT_TEST_SECRET" not in (r.output or {})


def test_api_code_test(client) -> None:  # type: ignore[no-untyped-def]
    resp = client.post(
        "/api/v1/nodes/code/test",
        json={"source": "def main(i):\n    return {'ok': True}", "input": {}},
    )
    assert resp.status_code == 200
    assert resp.json()["output"] == {"ok": True}


def test_api_failure_is_200_and_bad_request_is_422(client) -> None:  # type: ignore[no-untyped-def]
    resp = client.post("/api/v1/nodes/code/test", json={"source": "def main(", "input": 1})
    assert resp.status_code == 200 and resp.json()["error"]["type"] == "syntax_error"
    assert client.post("/api/v1/nodes/code/test", json={"input": 1}).status_code == 422


def test_non_loopback_bind_refused() -> None:
    with pytest.raises(SystemExit):
        Settings(host="0.0.0.0").assert_safe_bind()
    with pytest.raises(SystemExit):  # remote bind without a token is still refused
        Settings(host="0.0.0.0", allow_unsafe_remote=True).assert_safe_bind()
    Settings(host="0.0.0.0", allow_unsafe_remote=True, api_token="t").assert_safe_bind()
