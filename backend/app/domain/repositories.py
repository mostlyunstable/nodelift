"""Persistence boundary. The engine and services depend on these, not on SQLAlchemy."""

from typing import Any, Protocol

from app.domain.records import (
    RunRecord,
    RunSummary,
    VersionRecord,
    VersionSummary,
    WorkflowRecord,
    WorkflowSummary,
)
from app.domain.run import NodeExecution, RunEvent, RunStatus
from app.domain.workflow import WorkflowDefinition


class RevisionConflict(Exception):
    def __init__(self, current: int) -> None:
        super().__init__(f"stale revision, current is {current}")
        self.current = current


class WorkflowRepository(Protocol):
    def create(self, name: str, draft: WorkflowDefinition) -> WorkflowRecord: ...
    def get(self, workflow_id: str) -> WorkflowRecord | None: ...
    def list_all(self) -> list[WorkflowSummary]: ...
    def update_draft(
        self, workflow_id: str, name: str, draft: WorkflowDefinition, expected_revision: int
    ) -> WorkflowRecord | None: ...  # raises RevisionConflict
    def delete(self, workflow_id: str) -> bool: ...
    def add_version(
        self, workflow_id: str, definition: WorkflowDefinition, content_hash: str
    ) -> VersionRecord: ...
    def latest_version(self, workflow_id: str) -> VersionRecord | None: ...
    def get_version(self, workflow_id: str, version_no: int) -> VersionRecord | None: ...
    def list_versions(self, workflow_id: str) -> list[VersionSummary]: ...


class RunRepository(Protocol):
    def create(
        self, run_id: str, workflow_id: str, version: VersionRecord, run_input: Any
    ) -> RunRecord: ...
    def add_node_execution(self, run_id: str, seq: int, record: NodeExecution) -> None: ...
    def finish(self, run_id: str, status: RunStatus, duration_ms: int) -> None: ...
    def add_event(self, run_id: str, type: str, payload: dict[str, Any]) -> RunEvent: ...
    def list_events(self, run_id: str, after_seq: int = 0, limit: int = 500) -> list[RunEvent]: ...
    def prune_runs(self, workflow_id: str, keep: int) -> int: ...  # delete the oldest beyond `keep`
    def mark_stale_running(self) -> list[str]: ...  # runs left "running" by a crashed server
    def get(self, run_id: str) -> RunRecord | None: ...
    def list_for_workflow(self, workflow_id: str, limit: int = 50) -> list[RunSummary]: ...
