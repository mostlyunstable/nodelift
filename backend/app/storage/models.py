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


class RunEventRow(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "seq"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
