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
    analysis_status: str  # not_analyzed | analyzing | done | partial | failed | cancelled
    analysis_error: str | None
    edge_count: int
    diagnostic_count: int
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


class RepoEdgeRecord(BaseModel):
    """A relationship found by static analysis, with how sure we are and who says so."""

    src: str
    dst: str | None  # None when the target is outside the repository or could not be resolved
    kind: str  # import | dynamic_import | reexport | reference | style_import | tests
    confidence: str  # resolved | heuristic | unresolved | external
    line: int
    raw: str  # the specifier as written
    provenance: str  # which analyzer produced it
    note: str | None = None


class RepoSymbolRecord(BaseModel):
    path: str
    name: str
    kind: str  # function | class | method | interface | type | enum | variable
    line: int
    end_line: int
    parent: str | None = None
    exported: bool = True


class RepoDiagnosticRecord(BaseModel):
    path: str
    line: int
    column: int
    severity: str  # error | warning | info
    code: str
    message: str
    source: str


class FileAnalysisRecord(BaseModel):
    path: str
    status: str
    symbols: list[RepoSymbolRecord]
    imports: list[RepoEdgeRecord]  # outgoing, including external and unresolved
    dependents: list[RepoEdgeRecord]  # incoming, resolved inside the repository
    diagnostics: list[RepoDiagnosticRecord]


class RepoGraphRecord(BaseModel):
    edges: list[RepoEdgeRecord]  # only edges between two files of the repository
    truncated: bool
    diagnostics: list[RepoDiagnosticRecord]
