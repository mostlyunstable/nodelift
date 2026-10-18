import hashlib
import json
from typing import Any

from app.api.errors import AppError
from app.domain.ports import CodeRunner
from app.domain.records import RunRecord, VersionRecord
from app.domain.repositories import RunRepository, WorkflowRepository
from app.domain.workflow import WorkflowDefinition, validate_workflow
from app.engine.executor import execute_workflow


def content_hash(defn: WorkflowDefinition) -> str:
    """Hash of what affects execution; layout (`ui`) is excluded."""
    canonical = json.dumps(
        defn.model_dump(mode="json", exclude={"ui"}), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class WorkflowService:
    def __init__(
        self, workflows: WorkflowRepository, runs: RunRepository, runner: CodeRunner
    ) -> None:
        self.workflows, self.runs, self.runner = workflows, runs, runner

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

    async def run(
        self, workflow_id: str, version_no: int | None, run_input: Any, timeout_s: float
    ) -> RunRecord:
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
        result = await execute_workflow(version.definition, self.runner, run_input, timeout_s)
        return self.runs.save(workflow_id, version, run_input, result)
