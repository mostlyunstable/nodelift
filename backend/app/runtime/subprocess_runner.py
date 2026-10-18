"""Runs user Python in a child process. NOT a sandbox: trusted local-dev mode only.

Safeguards: scrubbed env, isolated interpreter (-I), temp cwd, own process group
(killed on timeout), CPU/core rlimits, capped output and log sizes.
"""

import asyncio
import json
import os
import resource
import signal
import sys
import tempfile
import time
from pathlib import Path

from app.domain.ports import CodeRunResult, JsonValue, LogLine, NodeError

WORKER = Path(__file__).with_name("worker_entry.py")
MAX_RESULT_BYTES = 5 * 1024 * 1024
MAX_LOG_BYTES = 64 * 1024
MAX_LOG_LINES = 1000


def _limits(cpu_s: int) -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 1))


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


class SubprocessRunner:
    async def run(self, source: str, input_data: JsonValue, timeout_s: float) -> CodeRunResult:
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

        r_fd, w_fd = os.pipe()
        with tempfile.TemporaryDirectory(prefix="nodecraft-") as cwd:
            try:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-I",
                    str(WORKER),
                    str(w_fd),
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
                    preexec_fn=lambda: _limits(int(timeout_s) + 1),
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

            try:
                (res, res_trunc), (out, _), (err, _), _, _ = await asyncio.wait_for(
                    asyncio.gather(
                        _read_capped(result_reader, MAX_RESULT_BYTES),
                        _read_capped(proc.stdout, MAX_LOG_BYTES),
                        _read_capped(proc.stderr, MAX_LOG_BYTES),
                        feed(),
                        proc.wait(),
                    ),
                    timeout=timeout_s,
                )
            except TimeoutError:
                _kill_group(proc)
                await proc.wait()
                return done(NodeError(type="timeout", message=f"Exceeded {timeout_s:g}s limit"))
            finally:
                _kill_group(proc)  # reap any grandchildren
                transport.close()

        logs = (_logs("stdout", out) + _logs("stderr", err))[:MAX_LOG_LINES]
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
