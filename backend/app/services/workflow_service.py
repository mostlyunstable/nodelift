import asyncio
import hashlib
import json
import logging
import uuid
from typing import Any

from app.api.errors import AppError
from app.domain.ports import CodeRunner
from app.domain.records import RunRecord, VersionRecord
from app.domain.repositories import RunRepository, WorkflowRepository
from app.domain.run import NodeExecution
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

    async def node_started(self, node_id: str) -> None:
        await self.emit("node.started", {"node_id": node_id})

    async def node_finished(self, record: NodeExecution) -> None:
        self.runs.add_node_execution(self.run_id, self._seq, record)
        self._seq += 1
        await self.emit(
            "node.finished",
            {
                "node_id": record.node_id,
                "status": record.status,
                "duration_ms": record.duration_ms,
                "error_type": record.error.type if record.error else None,
            },
        )


class WorkflowService:
    def __init__(
        self,
        workflows: WorkflowRepository,
        runs: RunRepository,
        runner: CodeRunner,
        hub: RunHub,
    ) -> None:
        self.workflows, self.runs, self.runner, self.hub = workflows, runs, runner, hub

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
        issues = validate_workflow(version.definition)
        if issues:
            raise AppError(
                422, "validation_failed", "Workflow is invalid", [i.model_dump() for i in issues]
            )
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        record = self.runs.create(run_id, workflow_id, version, run_input)
        recorder = RunRecorder(run_id, self.runs, self.hub)
        await recorder.emit("run.started", {"version_no": version.version_no})
        self.hub.track(
            asyncio.create_task(self._execute(version, run_input, timeout_s, recorder, run_id))
        )
        return record

    async def _execute(
        self,
        version: VersionRecord,
        run_input: Any,
        timeout_s: float,
        recorder: RunRecorder,
        run_id: str,
    ) -> None:
        try:
            result = await execute_workflow(
                version.definition,
                self.runner,
                run_input,
                timeout_s,
                observer=recorder,
                run_id=run_id,
            )
            self.runs.finish(run_id, result.status, result.duration_ms)
            await recorder.emit(
                "run.finished", {"status": result.status, "duration_ms": result.duration_ms}
            )
        except Exception:
            log.exception("run %s crashed", run_id)
            self.runs.finish(run_id, "failed", 0)
            await recorder.emit("run.finished", {"status": "failed", "reason": "internal_error"})
        finally:
            self.hub.forget(run_id)
