"""`python -m app` must start and stop deterministically (no reloader child holding the port)."""

import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def children(pid: int) -> list[int]:
    out = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True).stdout
    return [int(x) for x in out.split()]


def start(tmp_path: Path, **extra: str) -> tuple[subprocess.Popen[bytes], int]:
    port = free_port()
    env = {
        **os.environ,
        "NODECRAFT_PORT": str(port),
        "NODECRAFT_DATA_DIR": str(tmp_path),
        "NODECRAFT_ALLOWED_HOSTS": "127.0.0.1,localhost",
        **extra,
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "app"], cwd=BACKEND, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/health", timeout=1) as r:
                if r.status == 200:
                    return proc, port
        except OSError:
            time.sleep(0.2)
    proc.kill()
    raise AssertionError("server did not become healthy")


def wait_closed(port: int, timeout: float = 8) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not listening(port):
            return True
        time.sleep(0.1)
    return False


def test_default_start_has_no_reloader_and_stops_cleanly(tmp_path: Path) -> None:
    proc, port = start(tmp_path)
    try:
        assert children(proc.pid) == []  # a reloader would show up as a child process
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=10) is not None
        assert wait_closed(port), "port still open after SIGTERM"
    finally:
        proc.kill()


def test_killing_the_server_frees_the_port(tmp_path: Path) -> None:
    """The bug this guards against: with reload=True, SIGKILL on the parent left a child serving."""
    proc, port = start(tmp_path)
    try:
        proc.kill()
        proc.wait(timeout=5)
        assert wait_closed(port, 5), "something still listens after the server was killed"
    finally:
        proc.kill()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_reload_is_opt_in(tmp_path: Path) -> None:
    proc, port = start(tmp_path, NODECRAFT_RELOAD="1")
    try:
        assert children(proc.pid), "NODECRAFT_RELOAD=1 should start the reloader"
    finally:
        proc.kill()
        subprocess.run(["pkill", "-9", "-f", f"multiprocessing.spawn.*{port}"], check=False)
        subprocess.run(["pkill", "-9", "-f", "multiprocessing.spawn"], check=False)
        wait_closed(port)
