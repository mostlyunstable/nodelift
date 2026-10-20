# ruff: noqa: E501
"""Run one explicitly approved command inside a prepared workspace, confined by the OS where possible.

Nothing here is reachable without the caller restating the exact command (see the API layer). The
command never gets Nodecraft's environment, secrets or home folder (unless the user ticks that box),
has no network by default, and can write only inside the workspace and a scratch folder. Packages are
never installed by Nodecraft itself; a command that tries to, fails without network.
"""

import asyncio
import contextlib
import os
import resource
import shlex
import shutil
import signal
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.domain.errors import AppError
from app.domain.records import CommandRunRecord
from app.explorer.discovery import risk_notes
from app.runtime import sandbox
from app.runtime.subprocess_runner import watch_memory

MAX_OUTPUT = 256 * 1024
MAX_TIMEOUT_S = 900
SYSTEM_PATH = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]


@dataclass
class _Run:
    id: str
    revision_id: str
    argv: list[str]
    cwd: str
    started: datetime
    confinement: dict[str, object]
    notes: list[str]
    status: str = "running"
    exit_code: int | None = None
    ended: datetime | None = None
    output: bytearray = field(default_factory=bytearray)
    truncated: bool = False
    proc: asyncio.subprocess.Process | None = None
    cancelled: bool = False
    task: asyncio.Task[None] | None = None


class CommandRuns:
    """Live and recent command runs (kept in memory; they are not durable history)."""

    def __init__(self, sandbox_mode: str = "auto") -> None:
        self.sandbox_mode = sandbox_mode
        self.runs: dict[str, _Run] = {}
        self.lock = asyncio.Semaphore(1)  # one approved command at a time

    async def shutdown(self) -> None:
        for r in self.runs.values():
            if r.proc and r.proc.returncode is None:
                r.cancelled = True
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(r.proc.pid, signal.SIGKILL)

    # ------------------------------------------------------------------------------------
    def _path(self, allow_home: bool) -> str:
        home = str(Path.home())
        extra = [
            p
            for p in os.environ.get("PATH", "").split(":")
            if p and (allow_home or not p.startswith(home))
        ]
        out: list[str] = []
        for p in [*SYSTEM_PATH, *extra]:
            if p not in out and Path(p).is_dir():
                out.append(p)
        return ":".join(out)

    def _resolve(self, argv: list[str], cwd: Path, root: Path, path_env: str) -> str:
        exe = argv[0]
        if "/" in exe:
            target = (cwd / exe).resolve()
            if root.resolve() not in target.parents or not target.is_file():
                raise AppError(
                    422, "invalid_command", "A path in the command must point inside the workspace"
                )
            return str(target)
        found = shutil.which(exe, path=path_env)
        if not found:
            raise AppError(
                422,
                "command_not_found",
                f"{exe!r} was not found on this machine (looked in: {path_env})",
            )
        return found

    def record(self, r: _Run) -> CommandRunRecord:
        return CommandRunRecord(
            id=r.id, revision_id=r.revision_id, command=shlex.join(r.argv), argv=r.argv, cwd=r.cwd,
            status=r.status, exit_code=r.exit_code, started_at=r.started, ended_at=r.ended,
            output=r.output.decode("utf-8", "replace"), output_truncated=r.truncated,
            confinement=r.confinement, notes=r.notes,
        )  # fmt: skip

    def get(self, run_id: str, revision_id: str) -> _Run:
        r = self.runs.get(run_id)
        if r is None or r.revision_id != revision_id:
            raise AppError(404, "not_found", "Command run not found")
        return r

    def list_for(self, revision_id: str) -> list[_Run]:
        return sorted(
            (r for r in self.runs.values() if r.revision_id == revision_id), key=lambda r: r.started
        )

    def cancel(self, run_id: str, revision_id: str) -> _Run:
        r = self.get(run_id, revision_id)
        if r.proc and r.proc.returncode is None:
            r.cancelled = True
            with contextlib.suppress(ProcessLookupError):
                os.killpg(r.proc.pid, signal.SIGKILL)
        return r

    # ------------------------------------------------------------------------------------
    async def start(
        self,
        revision_id: str,
        workspace: Path,
        command: str,
        cwd_rel: str,
        timeout_s: float,
        allow_network: bool,
        allow_home_read: bool,
        acknowledge_unconfined: bool,
    ) -> _Run:
        try:
            argv = shlex.split(command)
        except ValueError as e:
            raise AppError(422, "invalid_command", f"The command could not be parsed: {e}") from e
        if not argv:
            raise AppError(422, "invalid_command", "The command is empty")
        cwd = (workspace / cwd_rel).resolve()
        if workspace.resolve() not in {cwd, *cwd.parents} or not cwd.is_dir():
            raise AppError(
                422, "invalid_command", "The working folder must be inside the workspace"
            )
        confined = self.sandbox_mode != "off" and sandbox.available()
        if self.sandbox_mode == "required" and not sandbox.available():
            raise AppError(
                409, "sandbox_unavailable", "Sandboxing is required but is not available"
            )
        if not confined and not acknowledge_unconfined:
            raise AppError(
                409,
                "unconfined_needs_acknowledgement",
                "This machine cannot confine commands, so this one would run with your full permissions. "
                "Acknowledge that explicitly to continue.",
            )
        timeout_s = max(1.0, min(float(timeout_s), MAX_TIMEOUT_S))
        path_env = self._path(allow_home_read)
        exe = self._resolve(argv, cwd, workspace, path_env)
        scratch = Path(tempfile.mkdtemp(prefix="nodecraft-cmd-")).resolve()
        run = _Run(
            id=f"cmd_{uuid.uuid4().hex[:10]}", revision_id=revision_id, argv=argv, cwd=cwd_rel,
            started=datetime.now(UTC),
            confinement={
                "confined": confined, "network": allow_network, "home_readable": allow_home_read or not confined,
                "writes": [str(workspace), "a temporary folder"] if confined else ["anywhere you can"],
                "timeout_s": timeout_s,
            },
            notes=risk_notes(argv),
        )  # fmt: skip
        self.runs[run.id] = run
        full = [exe, *argv[1:]]
        if confined:
            exe_real = Path(exe).resolve()
            profile = sandbox.build_profile(
                scratch,
                [exe_real.parent, exe_real.parent.parent, *(Path(p) for p in path_env.split(":"))],
                allow_network=allow_network,
                write_roots=[workspace],
                protect_home=not allow_home_read,
            )
            full = sandbox.wrap(full, profile)
        env = {
            "PATH": path_env, "HOME": str(scratch), "TMPDIR": str(scratch), "LANG": "en_US.UTF-8",
            "CI": "1", "NO_COLOR": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
        }  # fmt: skip
        run.task = asyncio.create_task(self._run(run, full, cwd, env, scratch, timeout_s))
        return run

    async def _run(
        self,
        run: _Run,
        full: list[str],
        cwd: Path,
        env: dict[str, str],
        scratch: Path,
        timeout_s: float,
    ) -> None:
        async with self.lock:
            try:
                run.proc = await asyncio.create_subprocess_exec(
                    *full, cwd=cwd, env=env, stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                    start_new_session=True, preexec_fn=_limits,
                )  # fmt: skip
            except OSError as e:
                run.status, run.exit_code, run.ended = "failed", None, datetime.now(UTC)
                run.output += f"Could not start the command: {e}\n".encode()
                shutil.rmtree(scratch, ignore_errors=True)
                return
            proc = run.proc
            assert proc.stdout
            mem = asyncio.Event()
            dog = (
                asyncio.ensure_future(watch_memory(proc, 4096, mem))
                if sys.platform == "darwin"
                else None
            )

            async def pump() -> None:
                assert proc.stdout
                while chunk := await proc.stdout.read(65536):
                    room = MAX_OUTPUT - len(run.output)
                    if room > 0:
                        run.output += chunk[:room]
                    if len(chunk) > room:
                        run.truncated = True

            try:
                await asyncio.wait_for(asyncio.gather(pump(), proc.wait()), timeout=timeout_s)
                run.exit_code = proc.returncode
                if run.cancelled:
                    run.status = "cancelled"
                elif mem.is_set():
                    run.status = "failed"
                    run.output += b"\n[Nodecraft] stopped: more than 4 GB of memory\n"
                else:
                    run.status = "succeeded" if proc.returncode == 0 else "failed"
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
                await proc.wait()
                run.status, run.exit_code = "timeout", proc.returncode
                run.output += f"\n[Nodecraft] stopped: exceeded {timeout_s:g}s\n".encode()
            finally:
                if dog:
                    dog.cancel()
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)  # reap grandchildren
                run.ended = datetime.now(UTC)
                shutil.rmtree(scratch, ignore_errors=True)


def _limits() -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (1024, 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (512 << 20, 512 << 20))
