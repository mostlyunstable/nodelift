from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Dialect,
    ForeignKey,
    Integer,
    String,
    TypeDecorator,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Always stores UTC and always returns timezone-aware UTC.

    SQLite drops tzinfo, so a plain DateTime comes back naive and clients misread it as local time.
    Rows written before this type existed are naive UTC, which this reads correctly.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Base(DeclarativeBase):
    pass


class WorkflowRow(Base):
    __tablename__ = "workflows"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    draft: Mapped[dict[str, Any]] = mapped_column(JSON)  # mutable working copy
    revision: Mapped[int] = mapped_column(Integer, default=1)  # optimistic concurrency
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class WorkflowVersionRow(Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (UniqueConstraint("workflow_id", "version_no"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    version_no: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON)  # immutable snapshot
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class RunRow(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    version_id: Mapped[str] = mapped_column(ForeignKey("workflow_versions.id"))
    version_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String)
    input: Mapped[Any] = mapped_column(JSON, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class NodeExecutionRow(Base):
    __tablename__ = "node_executions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    node_id: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    input: Mapped[Any] = mapped_column(JSON, nullable=True)
    output: Mapped[Any] = mapped_column(JSON, nullable=True)
    logs: Mapped[list[Any]] = mapped_column(JSON)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer)
    attempt: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    reused: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    activated_ports: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    skip_reason: Mapped[str | None] = mapped_column(String, nullable=True)


class CredentialRow(Base):
    """Metadata only. The secret value is never stored here (see SecretStore)."""

    __tablename__ = "credentials"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    kind: Mapped[str] = mapped_column(String, default="other")
    description: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class RunEventRow(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "seq"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class RepoRevisionRow(Base):
    __tablename__ = "repo_revisions"
    __table_args__ = (UniqueConstraint("owner", "repo", "commit_sha"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    owner: Mapped[str] = mapped_column(String)
    repo: Mapped[str] = mapped_column(String)
    full_name: Mapped[str] = mapped_column(String)
    branch: Mapped[str] = mapped_column(String)
    default_branch: Mapped[str] = mapped_column(String)
    commit_sha: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String)
    phase: Mapped[str] = mapped_column(String, default="")
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    text_count: Mapped[int] = mapped_column(Integer, default=0)
    binary_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    total_bytes: Mapped[int] = mapped_column(Integer, default=0)
    analyzed_count: Mapped[int] = mapped_column(Integer, default=0)
    analysis_status: Mapped[str] = mapped_column(String, default="not_analyzed")
    analysis_error: Mapped[str | None] = mapped_column(String, nullable=True)
    edge_count: Mapped[int] = mapped_column(Integer, default=0)
    diagnostic_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class RepoFileRow(Base):
    __tablename__ = "repo_files"
    __table_args__ = (UniqueConstraint("revision_id", "path"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("repo_revisions.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String)
    language: Mapped[str] = mapped_column(String)
    size: Mapped[int] = mapped_column(Integer)
    lines: Mapped[int] = mapped_column(Integer)
    binary: Mapped[bool] = mapped_column(Boolean)
    stored: Mapped[bool] = mapped_column(Boolean)
    skip_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    analysis_status: Mapped[str] = mapped_column(String, default="not_analyzed")


class RepoEdgeRow(Base):
    __tablename__ = "repo_edges"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("repo_revisions.id", ondelete="CASCADE"), index=True
    )
    src: Mapped[str] = mapped_column(String, index=True)
    dst: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String)
    confidence: Mapped[str] = mapped_column(String)
    line: Mapped[int] = mapped_column(Integer)
    raw: Mapped[str] = mapped_column(String)
    provenance: Mapped[str] = mapped_column(String)
    note: Mapped[str | None] = mapped_column(String, nullable=True)


class RepoSymbolRow(Base):
    __tablename__ = "repo_symbols"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("repo_revisions.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    parent: Mapped[str | None] = mapped_column(String, nullable=True)
    exported: Mapped[bool] = mapped_column(Boolean, default=True)


class RepoDiagnosticRow(Base):
    __tablename__ = "repo_diagnostics"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("repo_revisions.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String, index=True)
    line: Mapped[int] = mapped_column(Integer)
    column: Mapped[int] = mapped_column(Integer)
    severity: Mapped[str] = mapped_column(String)
    code: Mapped[str] = mapped_column(String)
    message: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)


class RepoPatchRow(Base):
    __tablename__ = "repo_patches"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("repo_revisions.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    new_content: Mapped[str] = mapped_column(String)
    additions: Mapped[int] = mapped_column(Integer, default=0)
    deletions: Mapped[int] = mapped_column(Integer, default=0)
    applied: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    applied_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class RepoReferenceRow(Base):
    __tablename__ = "repo_references"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("repo_revisions.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String, index=True)
    line: Mapped[int] = mapped_column(Integer)
    column: Mapped[int] = mapped_column(Integer)
    end_column: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    scope: Mapped[str | None] = mapped_column(String, nullable=True)
    dst_path: Mapped[str] = mapped_column(String, index=True)
    dst_symbol: Mapped[str] = mapped_column(String)
    dst_line: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[str] = mapped_column(String)
    provenance: Mapped[str] = mapped_column(String)
    note: Mapped[str | None] = mapped_column(String, nullable=True)


class TriggerRow(Base):
    """A schedule or a webhook that starts a workflow; a webhook token is stored only as a hash."""

    __tablename__ = "triggers"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String)
    every_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    daily_at: Mapped[str | None] = mapped_column(String, nullable=True)
    token_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
