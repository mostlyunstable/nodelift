# ruff: noqa: E501
"""The confinement is verified from the inside: user code tries to escape and the kernel says no."""

import asyncio
import os
import socket
import sys
import threading
from pathlib import Path

import pytest

from app.runtime import sandbox
from app.runtime.subprocess_runner import SubprocessRunner

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin" or not sandbox.available(), reason="needs macOS Seatbelt"
)

PROBE = """
import os, socket, tempfile
def attempt(f):
    try:
        f()
        return "allowed"
    except Exception as e:
        return "denied:" + type(e).__name__
def main(input_data):
    home = os.path.expanduser("~")
    return {
        "compute": sum(range(100)),
        "scratch_write": attempt(lambda: open(os.path.join(os.getcwd(), "ok.txt"), "w").write("x")),
        "home_write": attempt(lambda: open(os.path.join(home, input_data["canary_write"]), "w").write("x")),
        "tmp_write": attempt(lambda: open(input_data["tmp_write"], "w").write("x")),
        "home_read": attempt(lambda: open(input_data["secret"]).read()),
        "home_list": attempt(lambda: os.listdir(home)),
        "network": attempt(lambda: socket.create_connection(("127.0.0.1", input_data["port"]), timeout=2)),
        "dns": attempt(lambda: socket.getaddrinfo("example.com", 80)),
    }
"""


@pytest.fixture
def listener() -> "tuple[int, list[int]]":
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    hits: list[int] = []

    def accept() -> None:
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            hits.append(1)
            c.close()

    threading.Thread(target=accept, daemon=True).start()
    yield srv.getsockname()[1], hits  # type: ignore[misc]
    srv.close()


def run(runner: SubprocessRunner, source: str, data: object, **kw: object) -> dict:
    res = asyncio.run(runner.run(source, data, 10, None, **kw))  # type: ignore[arg-type]
    assert res.error is None, res.error
    return res.output  # type: ignore[return-value]


def probe_input(listener: tuple[int, list[int]]) -> dict:
    home = Path.home()
    secret = home / f".nodecraft-sandbox-canary-{os.getpid()}"
    secret.write_text("top secret")
    return {
        "port": listener[0],
        "secret": str(secret),
        "canary_write": f".nodecraft-should-not-exist-{os.getpid()}",
        "tmp_write": f"/tmp/nodecraft-should-not-exist-{os.getpid()}",
    }


def test_sandboxed_code_cannot_touch_the_network_home_or_write_outside_scratch(
    listener: tuple[int, list[int]],
) -> None:
    data = probe_input(listener)
    try:
        out = run(SubprocessRunner(sandbox_mode="auto"), PROBE, data)
    finally:
        Path(data["secret"]).unlink(missing_ok=True)
    assert out["compute"] == 4950  # ordinary code still works
    assert out["scratch_write"] == "allowed"  # its own temp folder is writable
    for k in ("home_write", "tmp_write", "home_read", "home_list", "network", "dns"):
        assert out[k].startswith("denied"), (k, out[k])
    assert listener[1] == []  # the server never saw a connection
    assert not (Path.home() / data["canary_write"]).exists()
    assert not Path(data["tmp_write"]).exists()


def test_without_the_sandbox_the_same_code_escapes(listener: tuple[int, list[int]]) -> None:
    """The control: proves the probe above really can do these things when unconfined."""
    data = probe_input(listener)
    try:
        out = run(SubprocessRunner(sandbox_mode="off"), PROBE, data)
    finally:
        Path(data["secret"]).unlink(missing_ok=True)
        (Path.home() / data["canary_write"]).unlink(missing_ok=True)
        Path(data["tmp_write"]).unlink(missing_ok=True)
    assert out["home_read"] == "allowed" and out["network"] == "allowed"
    assert out["home_write"] == "allowed" and out["tmp_write"] == "allowed"


def test_network_is_opt_in(listener: tuple[int, list[int]]) -> None:
    data = probe_input(listener)
    try:
        out = run(SubprocessRunner(sandbox_mode="auto"), PROBE, data, allow_network=True)
    finally:
        Path(data["secret"]).unlink(missing_ok=True)
    assert out["network"] == "allowed"
    assert out["home_read"].startswith("denied")  # still no home access


def test_children_of_sandboxed_code_are_confined_too(listener: tuple[int, list[int]]) -> None:
    src = (
        "import subprocess, sys\n"
        "def main(i):\n"
        "    code = 'import socket,sys; socket.create_connection((\"127.0.0.1\",%d),timeout=2)' % i['port']\n"
        "    r = subprocess.run([sys.executable, '-c', code], capture_output=True)\n"
        "    return r.returncode\n"
    )
    out = run(SubprocessRunner(sandbox_mode="auto"), src, {"port": listener[0]})
    assert out != 0 and listener[1] == []


def test_required_mode_refuses_when_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sandbox, "available", lambda: False)
    res = asyncio.run(SubprocessRunner(sandbox_mode="required").run("def main(i): return 1", {}, 5))
    assert res.error and res.error.type == "invalid_config" and "required" in res.error.message


def test_status_reports_what_is_really_active() -> None:
    assert SubprocessRunner(sandbox_mode="auto").status()["active"] is True
    assert SubprocessRunner(sandbox_mode="off").status()["active"] is False


def test_memory_watchdog_kills_runaway_allocation() -> None:
    src = (
        "def main(i):\n"
        "    blocks = []\n"
        "    while True:\n"
        "        blocks.append(bytearray(50 * 1024 * 1024))\n"
        "        for b in blocks: b[::4096] = b'x' * len(b[::4096])\n"
    )
    res = asyncio.run(SubprocessRunner(memory_mb=300, sandbox_mode="auto").run(src, {}, 30))
    assert res.error and res.error.type == "memory_limit", res.error


def test_profile_rejects_paths_that_could_break_out_of_the_profile() -> None:
    with pytest.raises(sandbox.UnsafePath):
        sandbox.build_profile(Path('/tmp/a"b'), [])


def _workers() -> int:
    import subprocess

    out = subprocess.run(["/bin/ps", "-A", "-o", "command="], capture_output=True, text=True).stdout
    return sum(1 for line in out.splitlines() if "worker_entry.py" in line)


def test_a_sandboxed_worker_is_killed_on_timeout_and_leaves_no_process_behind() -> None:
    before = _workers()
    res = asyncio.run(
        SubprocessRunner(sandbox_mode="auto").run("def main(i):\n    while True: pass", {}, 0.8)
    )
    assert res.error and res.error.type == "timeout"
    assert _workers() == before
