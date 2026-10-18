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


class RunSummary(BaseModel):
    id: str
    status: str
    version_no: int
    duration_ms: int
    created_at: datetime
