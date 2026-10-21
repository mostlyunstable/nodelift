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


class RepoReferenceRecord(BaseModel):
    """A name use that static analysis tied to a definition (here or in another file)."""

    path: str
    line: int
    column: int  # 1-based start of the name
    end_column: int
    name: str
    kind: str  # call
    scope: str | None  # the function/method (qualified) that contains it; None at module level
    dst_path: str
    dst_symbol: str  # qualified, e.g. "Session.request"
    dst_line: int
    confidence: str  # resolved | heuristic
    provenance: str
    note: str | None = None


class FileAnalysisRecord(BaseModel):
    path: str
    status: str
    symbols: list[RepoSymbolRecord]
    references: list[RepoReferenceRecord] = []  # names in this file tied to a definition
    called_by: list[RepoReferenceRecord] = []  # call sites elsewhere that resolve into this file
    imports: list[RepoEdgeRecord]  # outgoing, including external and unresolved
    dependents: list[RepoEdgeRecord]  # incoming, resolved inside the repository
    diagnostics: list[RepoDiagnosticRecord]


class RepoGraphRecord(BaseModel):
    edges: list[RepoEdgeRecord]  # only edges between two files of the repository
    truncated: bool
    diagnostics: list[RepoDiagnosticRecord]


class RepoPatchRecord(BaseModel):
    """A change someone proposed to one file. The repository's own files are never modified."""

    id: str
    revision_id: str
    path: str
    title: str
    additions: int
    deletions: int
    applied: bool
    created_at: datetime
    applied_at: datetime | None


class WorkspaceRecord(BaseModel):
    state: str  # none | preparing | ready | failed
    path: str | None
    file_count: int
    error: str | None


class SuggestionRecord(BaseModel):
    id: str
    label: str
    argv: list[str]
    framework: str
    kind: str
    cwd: str
    evidence: str
    notes: list[str]


class DiscoveryRecord(BaseModel):
    suggestions: list[SuggestionRecord]
    test_files: list[str]
    frameworks: list[str]


class CommandRunRecord(BaseModel):
    id: str
    revision_id: str
    command: str
    argv: list[str]
    cwd: str
    status: str  # running | succeeded | failed | cancelled | timeout | blocked
    exit_code: int | None
    started_at: datetime
    ended_at: datetime | None
    output: str
    output_truncated: bool
    confinement: dict[str, object]
    notes: list[str]


class WorkflowDraftRecord(BaseModel):
    """A workflow node proposed from repository code. Nothing is saved until the user creates it."""

    name: str
    node_type: str
    config: dict[str, object]
    kind: str  # "copied implementation"
    provenance: dict[str, object]
    copied: list[dict[str, object]]
    warnings: list[str]
    params: list[str]


class TriggerRecord(BaseModel):
    """Something that starts a workflow by itself. The webhook token is never part of this."""

    id: str
    workflow_id: str
    kind: str  # "schedule" | "webhook"
    every_minutes: int | None = None  # schedule: every N minutes ...
    daily_at: str | None = None  # ... or once a day at HH:MM (this computer's local time)
    enabled: bool = True
    last_run_at: datetime | None = None
    last_run_id: str | None = None
    next_run_at: datetime | None = None
    created_at: datetime
