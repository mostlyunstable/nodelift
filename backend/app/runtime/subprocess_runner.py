"""Runs user Python in a child process.

Safeguards: scrubbed env, isolated interpreter (-I), temp cwd, own process group (killed on
timeout), CPU/core rlimits, capped output and log sizes, a memory watchdog on macOS, and on macOS
OS-level confinement (see `sandbox.py`) unless disabled. Without the sandbox the code runs with
the user's full permissions.
"""

import asyncio
import contextlib
import json
import os
import resource
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from app.domain.ports import CodeRunResult, JsonValue, LogLine, NodeError
from app.runtime import sandbox

WORKER = Path(__file__).with_name("worker_entry.py")
MAX_RESULT_BYTES = 5 * 1024 * 1024
MAX_LOG_BYTES = 64 * 1024
MAX_LOG_LINES = 1000


def _limits(cpu_s: int, memory_mb: int | None, max_file_mb: int) -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 1))
    resource.setrlimit(resource.RLIMIT_FSIZE, (max_file_mb << 20, max_file_mb << 20))
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    if memory_mb and sys.platform == "linux":  # macOS does not enforce RLIMIT_AS/RLIMIT_DATA
        resource.setrlimit(resource.RLIMIT_AS, (memory_mb << 20, memory_mb << 20))


async def _read_capped(stream: asyncio.StreamReader, cap: int) -> tuple[bytes, bool]:
    buf = bytearray()
    truncated = False
    while chunk := await stream.read(65536):
        if len(buf) < cap:
            buf += chunk[: cap - len(buf)]
        if len(buf) >= cap:
            truncated = True  # keep draining so the child never blocks on a full pipe
    return bytes(buf), truncated


def _logs(name: str, data: bytes) -> list[LogLine]:
    text = data.decode("utf-8", errors="replace")
    return [LogLine(stream=name, text=line) for line in text.splitlines()]  # type: ignore[arg-type]


def _kill_group(proc: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _group_rss_mb(pgid: int) -> float:
    """Resident memory of every process in a group, in MB (macOS/BSD `ps`)."""
    try:
        out = subprocess.run(
            ["/bin/ps", "-A", "-o", "pgid=,rss="], capture_output=True, text=True, timeout=3
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return 0.0
    total_kb = 0
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == str(pgid) and parts[1].isdigit():
            total_kb += int(parts[1])
    return total_kb / 1024


async def _watch_memory(
    proc: asyncio.subprocess.Process, limit_mb: int, tripped: asyncio.Event
) -> None:
    """macOS ignores RLIMIT_AS, so poll the group's memory and kill it past the limit."""
    while proc.returncode is None:
        await asyncio.sleep(0.2)
        if await asyncio.to_thread(_group_rss_mb, proc.pid) > limit_mb:
            tripped.set()
            _kill_group(proc)
            return


class SubprocessRunner:
    def __init__(
        self, memory_mb: int | None = None, max_file_mb: int = 10, sandbox_mode: str = "auto"
    ) -> None:
        self.memory_mb = memory_mb
        self.max_file_mb = max_file_mb
        self.sandbox_mode = sandbox_mode  # "auto" (use it if available), "off", "required"

    @property
    def sandboxed(self) -> bool:
        return self.sandbox_mode != "off" and sandbox.available()

    def status(self) -> dict[str, Any]:
        return {
            "mode": self.sandbox_mode,
            "active": self.sandboxed,
            "kind": "macos-seatbelt" if self.sandboxed else None,
            "memory_limit": "rlimit" if sys.platform == "linux" else "watchdog",
        }

    async def run(
        self,
        source: str,
        input_data: JsonValue,
        timeout_s: float,
        cancel: asyncio.Event | None = None,
        allow_network: bool = False,
    ) -> CodeRunResult:
        start = time.monotonic()

        def done(
            error: NodeError | None = None,
            output: JsonValue = None,
            logs: list[LogLine] | None = None,
        ) -> CodeRunResult:
            return CodeRunResult(
                status="failed" if error else "succeeded",
                output=output,
                logs=logs or [],
                duration_ms=int((time.monotonic() - start) * 1000),
                error=error,
            )

        try:
            request = json.dumps({"source": source, "input": input_data})
        except (TypeError, ValueError) as e:
            return done(NodeError(type="invalid_output", message=f"Input is not JSON: {e}"))

        if self.sandbox_mode == "required" and not sandbox.available():
            return done(
                NodeError(
                    type="invalid_config",
                    message="Sandboxing is required but is not available on this machine",
                )
            )
        r_fd, w_fd = os.pipe()
        with tempfile.TemporaryDirectory(prefix="nodecraft-") as cwd:
            argv = [sys.executable, "-I", str(WORKER), str(w_fd)]
            if self.sandboxed:
                profile = sandbox.build_profile(
                    Path(cwd),
                    [*sandbox.python_read_roots(), WORKER.parent],
                    allow_network=allow_network,
                )
                argv = sandbox.wrap(argv, profile)
            try:
                proc = await asyncio.create_subprocess_exec(
                    *argv,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    env={
                        "PATH": "/usr/bin:/bin",
                        "PYTHONIOENCODING": "utf-8",
                        "PYTHONDONTWRITEBYTECODE": "1",
                    },
                    pass_fds=(w_fd,),
                    start_new_session=True,
                    preexec_fn=lambda: _limits(
                        int(timeout_s) + 1, self.memory_mb, self.max_file_mb
                    ),
                )
            finally:
                os.close(w_fd)
            loop = asyncio.get_running_loop()
            result_reader = asyncio.StreamReader()
            transport, _ = await loop.connect_read_pipe(
                lambda: asyncio.StreamReaderProtocol(result_reader), os.fdopen(r_fd, "rb")
            )
            assert proc.stdin and proc.stdout and proc.stderr

            async def feed() -> None:
                try:
                    proc.stdin.write(request.encode())  # type: ignore[union-attr]
                    await proc.stdin.drain()  # type: ignore[union-attr]
                    proc.stdin.close()  # type: ignore[union-attr]
                except (BrokenPipeError, ConnectionResetError):
                    pass

            work = asyncio.ensure_future(
                asyncio.gather(
                    _read_capped(result_reader, MAX_RESULT_BYTES),
                    _read_capped(proc.stdout, MAX_LOG_BYTES),
                    _read_capped(proc.stderr, MAX_LOG_BYTES),
                    feed(),
                    proc.wait(),
                )
            )
            cancel_wait = asyncio.ensure_future(cancel.wait()) if cancel else None
            mem_tripped = asyncio.Event()
            watchdog = (
                asyncio.ensure_future(_watch_memory(proc, self.memory_mb, mem_tripped))
                if self.memory_mb and sys.platform == "darwin"
                else None
            )
            try:
                waiting: set[asyncio.Future[Any]] = {work}
                if cancel_wait:
                    waiting.add(cancel_wait)
                finished, _ = await asyncio.wait(
                    waiting, timeout=timeout_s, return_when=asyncio.FIRST_COMPLETED
                )
                if work not in finished:
                    _kill_group(proc)
                    work.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await work
                    await proc.wait()
                    if cancel_wait and cancel_wait in finished:
                        return done(NodeError(type="cancelled", message="Cancelled by user"))
                    return done(NodeError(type="timeout", message=f"Exceeded {timeout_s:g}s limit"))
                (res, res_trunc), (out, _), (err, _), _, _ = work.result()
            finally:
                if cancel_wait:
                    cancel_wait.cancel()
                if watchdog:
                    watchdog.cancel()
                _kill_group(proc)  # reap any grandchildren
                transport.close()

        logs = (_logs("stdout", out) + _logs("stderr", err))[:MAX_LOG_LINES]
        if mem_tripped.is_set():
            return done(
                NodeError(
                    type="memory_limit", message=f"Exceeded the {self.memory_mb} MB memory limit"
                ),
                logs=logs,
            )
        if res_trunc:
            return done(
                NodeError(type="output_too_large", message="Output exceeds 5 MB"), logs=logs
            )
        if not res:
            code = proc.returncode
            return done(
                NodeError(type="worker_crashed", message=f"Worker exited with code {code}"),
                logs=logs,
            )
        payload = json.loads(res)
        if payload["ok"]:
            return done(output=payload["output"], logs=logs)
        return done(NodeError(**payload["error"]), logs=logs)
