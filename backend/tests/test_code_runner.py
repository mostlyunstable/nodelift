import os
import subprocess

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


async def test_timeout_kills_child() -> None:
    marker = "nodecraft-timeout-marker-9137"
    r = await run(f"# {marker}\ndef main(i):\n    while True: pass", timeout=0.5)
    assert r.error and r.error.type == "timeout"
    out = subprocess.run(["pgrep", "-f", marker], capture_output=True)
    assert out.returncode != 0  # no orphan


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
    Settings(host="0.0.0.0", allow_unsafe_remote=True).assert_safe_bind()
