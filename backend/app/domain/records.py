from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.domain.run import ExecutionRun
from app.domain.workflow import WorkflowDefinition


class WorkflowRecord(BaseModel):
    id: str
    name: str
    draft: WorkflowDefinition
    revision: int
    created_at: datetime
    updated_at: datetime


class WorkflowSummary(BaseModel):
    id: str
    name: str
    revision: int
    updated_at: datetime


class VersionRecord(BaseModel):
    id: str
    workflow_id: str
    version_no: int
    content_hash: str
    definition: WorkflowDefinition
    created_at: datetime


class VersionSummary(BaseModel):
    version_no: int
    content_hash: str
    created_at: datetime


class RunRecord(ExecutionRun):
    workflow_id: str
    version_no: int
    input: Any = None
    created_at: datetime


class CredentialRecord(BaseModel):
    """What the API may show about a credential. There is deliberately no value field."""

    id: str
    name: str
    kind: str
    description: str
    created_at: datetime
    updated_at: datetime


class RunSummary(BaseModel):
    id: str
    status: str
    version_no: int
    duration_ms: int
    created_at: datetime


class RepoRevisionRecord(BaseModel):
    """One repository at one commit. Graphs and files always belong to exactly one revision."""

    schema_version: int = 1
    id: str
    owner: str
    repo: str
    full_name: str
    branch: str
    default_branch: str
    commit_sha: str
    description: str
    status: str  # importing | ready | failed | cancelled
    phase: str  # human-readable progress message
    file_count: int
    text_count: int
    binary_count: int
    skipped_count: int
    total_bytes: int
    analyzed_count: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class RepoFileRecord(BaseModel):
    path: str
    language: str
    size: int
    lines: int
    binary: bool
    stored: bool
    skip_reason: str | None
    analysis_status: str  # not_analyzed until a language analyzer runs (R4)
