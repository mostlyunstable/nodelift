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
from app.domain.run import ExecutionRun
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
    def save(
        self, workflow_id: str, version: VersionRecord, run_input: Any, run: ExecutionRun
    ) -> RunRecord: ...
    def get(self, run_id: str) -> RunRecord | None: ...
    def list_for_workflow(self, workflow_id: str, limit: int = 50) -> list[RunSummary]: ...
