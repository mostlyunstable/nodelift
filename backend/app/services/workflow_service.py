import asyncio
import hashlib
import json
import logging
import uuid
from typing import Any

from app.api.errors import AppError
from app.domain.nodes import NodeRegistry
from app.domain.records import RunRecord, VersionRecord
from app.domain.repositories import RunRepository, WorkflowRepository
from app.domain.run import NodeExecution, RunStatus
from app.domain.workflow import WorkflowDefinition, validate_workflow
from app.engine.executor import execute_workflow
from app.services.run_hub import RunHub

log = logging.getLogger("nodecraft.runs")


def content_hash(defn: WorkflowDefinition) -> str:
    """Hash of what affects execution; layout (`ui`) is excluded."""
    canonical = json.dumps(
        defn.model_dump(mode="json", exclude={"ui"}), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class RunRecorder:
    """Engine observer: persists each node execution, then records and announces an event."""

    def __init__(self, run_id: str, runs: RunRepository, hub: RunHub) -> None:
        self.run_id, self.runs, self.hub = run_id, runs, hub
        self._seq = 0

    async def emit(self, type: str, payload: dict[str, Any]) -> None:
        self.runs.add_event(self.run_id, type, payload)  # persisted before it is announced
        await self.hub.notify(self.run_id)

    async def node_started(self, node_id: str, attempt: int) -> None:
        await self.emit("node.started", {"node_id": node_id, "attempt": attempt})

    async def node_finished(self, record: NodeExecution, will_retry: bool) -> None:
        self.runs.add_node_execution(self.run_id, self._seq, record)
        self._seq += 1
        await self.emit(
            "node.finished",
            {
                "node_id": record.node_id,
                "status": record.status,
                "duration_ms": record.duration_ms,
                "error_type": record.error.type if record.error else None,
                "attempt": record.attempt,
                "will_retry": will_retry,
                "reused": record.reused,
            },
        )


class WorkflowService:
    def __init__(
        self,
        workflows: WorkflowRepository,
        runs: RunRepository,
        registry: NodeRegistry,
        hub: RunHub,
        max_concurrent_runs: int = 4,
        max_run_seconds: int = 300,
    ) -> None:
        self.workflows, self.runs, self.registry, self.hub = workflows, runs, registry, hub
        self.max_concurrent_runs = max_concurrent_runs
        self.max_run_seconds = max_run_seconds

    def snapshot(self, workflow_id: str) -> VersionRecord:
        """Create a version from the draft, or reuse the latest if the content is unchanged."""
        rec = self.workflows.get(workflow_id)
        if rec is None:
            raise AppError(404, "not_found", "Workflow not found")
        h = content_hash(rec.draft)
        latest = self.workflows.latest_version(workflow_id)
        if latest and latest.content_hash == h:
            return latest
        return self.workflows.add_version(workflow_id, rec.draft, h)

    async def start_run(
        self, workflow_id: str, version_no: int | None, run_input: Any, timeout_s: float
    ) -> RunRecord:
        """Create the run and start executing it in the background; returns immediately."""
        if version_no is None:
            version = self.snapshot(workflow_id)  # runs are always pinned to a saved version
        else:
            found = self.workflows.get_version(workflow_id, version_no)
            if found is None:
                raise AppError(404, "not_found", "Version not found")
            version = found
        return await self._launch(workflow_id, version, run_input, timeout_s)

    async def resume_run(self, run_id: str, timeout_s: float) -> RunRecord:
        """New run on the same pinned version that reuses nodes which already succeeded.

        Only succeeded nodes are reused, never re-run. A node that was in flight when the run
        died has no stored result and runs again, so its side effects may repeat unless it is
        idempotent.
        """
        src = self.runs.get(run_id)
        if src is None:
            raise AppError(404, "not_found", "Run not found")
        if src.status in ("running", "succeeded"):
            raise AppError(409, "not_resumable", f"A {src.status} run cannot be resumed")
        version = self.workflows.get_version(src.workflow_id, src.version_no)
        if version is None:
            raise AppError(404, "not_found", "Version not found")
        done = {n.node_id: n for n in src.nodes if n.status == "succeeded"}
        return await self._launch(
            src.workflow_id, version, src.input, timeout_s, completed=done, resumed_from=run_id
        )

    async def cancel_run(self, run_id: str) -> RunRecord:
        """Idempotent. Kills the running node and skips the rest; the run ends as `cancelled`."""
        run = self.runs.get(run_id)
        if run is None:
            raise AppError(404, "not_found", "Run not found")
        flag = self.hub.cancels.get(run_id)
        if flag is not None and not flag.is_set():
            flag.set()
            await RunRecorder(run_id, self.runs, self.hub).emit("run.cancel_requested", {})
        return run

    async def _launch(
        self,
        workflow_id: str,
        version: VersionRecord,
        run_input: Any,
        timeout_s: float,
        completed: dict[str, NodeExecution] | None = None,
        resumed_from: str | None = None,
    ) -> RunRecord:
        issues = validate_workflow(version.definition, self.registry)
        if issues:
            raise AppError(
                422, "validation_failed", "Workflow is invalid", [i.model_dump() for i in issues]
            )
        if len(self.hub.cancels) >= self.max_concurrent_runs:
            raise AppError(
                429, "too_many_runs", f"At most {self.max_concurrent_runs} runs at once; try later"
            )
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        record = self.runs.create(run_id, workflow_id, version, run_input)
        cancel = asyncio.Event()
        self.hub.cancels[run_id] = cancel
        recorder = RunRecorder(run_id, self.runs, self.hub)
        started: dict[str, Any] = {"version_no": version.version_no}
        if resumed_from:
            started |= {"resumed_from": resumed_from, "reused_nodes": sorted(completed or {})}
        await recorder.emit("run.started", started)
        self.hub.track(
            asyncio.create_task(
                self._execute(version, run_input, timeout_s, recorder, run_id, cancel, completed)
            )
        )
        return record

    async def _execute(
        self,
        version: VersionRecord,
        run_input: Any,
        timeout_s: float,
        recorder: RunRecorder,
        run_id: str,
        cancel: asyncio.Event,
        completed: dict[str, NodeExecution] | None,
    ) -> None:
        try:
            result = await execute_workflow(
                version.definition,
                self.registry,
                run_input,
                timeout_s,
                observer=recorder,
                run_id=run_id,
                cancel=cancel,
                max_run_s=self.max_run_seconds,
                completed=completed,
            )
            self.runs.finish(run_id, result.status, result.duration_ms)
            payload: dict[str, Any] = {"status": result.status, "duration_ms": result.duration_ms}
            if result.reason:
                payload["reason"] = result.reason
            await recorder.emit("run.finished", payload)
        except Exception:
            log.exception("run %s crashed", run_id)
            status: RunStatus = "failed"
            self.runs.finish(run_id, status, 0)
            await recorder.emit("run.finished", {"status": status, "reason": "internal_error"})
        finally:
            self.hub.cancels.pop(run_id, None)
            self.hub.forget(run_id)
