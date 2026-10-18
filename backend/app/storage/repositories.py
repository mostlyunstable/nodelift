import uuid
from typing import Any, cast

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.ports import LogLine, NodeError
from app.domain.records import (
    RunRecord,
    RunSummary,
    VersionRecord,
    VersionSummary,
    WorkflowRecord,
    WorkflowSummary,
)
from app.domain.repositories import RevisionConflict
from app.domain.run import ExecutionRun, NodeExecution, NodeStatus, RunStatus
from app.domain.workflow import WorkflowDefinition
from app.storage.models import (
    NodeExecutionRow,
    RunRow,
    WorkflowRow,
    WorkflowVersionRow,
    utcnow,
)


def _wf(r: WorkflowRow) -> WorkflowRecord:
    return WorkflowRecord(
        id=r.id,
        name=r.name,
        draft=WorkflowDefinition.model_validate(r.draft),
        revision=r.revision,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def _ver(r: WorkflowVersionRow) -> VersionRecord:
    return VersionRecord(
        id=r.id,
        workflow_id=r.workflow_id,
        version_no=r.version_no,
        content_hash=r.content_hash,
        definition=WorkflowDefinition.model_validate(r.definition),
        created_at=r.created_at,
    )


class SqlWorkflowRepository:
    def __init__(self, sf: sessionmaker[Session]) -> None:
        self.sf = sf

    def create(self, name: str, draft: WorkflowDefinition) -> WorkflowRecord:
        wid = f"wf_{uuid.uuid4().hex[:16]}"
        draft = draft.model_copy(update={"id": wid, "name": name})
        with self.sf.begin() as s:
            row = WorkflowRow(id=wid, name=name, draft=draft.model_dump(mode="json"))
            s.add(row)
            s.flush()
            return _wf(row)

    def get(self, workflow_id: str) -> WorkflowRecord | None:
        with self.sf() as s:
            row = s.get(WorkflowRow, workflow_id)
            return _wf(row) if row else None

    def list_all(self) -> list[WorkflowSummary]:
        with self.sf() as s:
            rows = s.scalars(select(WorkflowRow).order_by(WorkflowRow.updated_at.desc())).all()
            return [
                WorkflowSummary(id=r.id, name=r.name, revision=r.revision, updated_at=r.updated_at)
                for r in rows
            ]

    def update_draft(
        self, workflow_id: str, name: str, draft: WorkflowDefinition, expected_revision: int
    ) -> WorkflowRecord | None:
        with self.sf.begin() as s:
            row = s.get(WorkflowRow, workflow_id)
            if row is None:
                return None
            if row.revision != expected_revision:
                raise RevisionConflict(row.revision)
            row.name = name
            row.draft = draft.model_copy(update={"id": workflow_id, "name": name}).model_dump(
                mode="json"
            )
            row.revision += 1
            row.updated_at = utcnow()
            s.flush()
            return _wf(row)

    def delete(self, workflow_id: str) -> bool:
        with self.sf.begin() as s:
            # runs reference versions without cascade, so remove runs first
            s.execute(delete(RunRow).where(RunRow.workflow_id == workflow_id))
            row = s.get(WorkflowRow, workflow_id)
            if row is None:
                return False
            s.delete(row)
            return True

    def add_version(
        self, workflow_id: str, definition: WorkflowDefinition, content_hash: str
    ) -> VersionRecord:
        with self.sf.begin() as s:
            current = s.scalar(
                select(func.max(WorkflowVersionRow.version_no)).where(
                    WorkflowVersionRow.workflow_id == workflow_id
                )
            )
            row = WorkflowVersionRow(
                id=f"ver_{uuid.uuid4().hex[:16]}",
                workflow_id=workflow_id,
                version_no=(current or 0) + 1,
                content_hash=content_hash,
                definition=definition.model_dump(mode="json"),
            )
            s.add(row)
            s.flush()
            return _ver(row)

    def latest_version(self, workflow_id: str) -> VersionRecord | None:
        with self.sf() as s:
            row = s.scalars(
                select(WorkflowVersionRow)
                .where(WorkflowVersionRow.workflow_id == workflow_id)
                .order_by(WorkflowVersionRow.version_no.desc())
                .limit(1)
            ).first()
            return _ver(row) if row else None

    def get_version(self, workflow_id: str, version_no: int) -> VersionRecord | None:
        with self.sf() as s:
            row = s.scalars(
                select(WorkflowVersionRow).where(
                    WorkflowVersionRow.workflow_id == workflow_id,
                    WorkflowVersionRow.version_no == version_no,
                )
            ).first()
            return _ver(row) if row else None

    def list_versions(self, workflow_id: str) -> list[VersionSummary]:
        with self.sf() as s:
            rows = s.scalars(
                select(WorkflowVersionRow)
                .where(WorkflowVersionRow.workflow_id == workflow_id)
                .order_by(WorkflowVersionRow.version_no.desc())
            ).all()
            return [
                VersionSummary(
                    version_no=r.version_no, content_hash=r.content_hash, created_at=r.created_at
                )
                for r in rows
            ]


class SqlRunRepository:
    def __init__(self, sf: sessionmaker[Session]) -> None:
        self.sf = sf

    def save(
        self, workflow_id: str, version: VersionRecord, run_input: Any, run: ExecutionRun
    ) -> RunRecord:
        with self.sf.begin() as s:
            row = RunRow(
                id=run.id,
                workflow_id=workflow_id,
                version_id=version.id,
                version_no=version.version_no,
                status=run.status,
                input=run_input,
                duration_ms=run.duration_ms,
            )
            s.add(row)
            s.flush()  # no ORM relationship, so order inserts explicitly (FK run_id)
            for seq, n in enumerate(run.nodes):
                s.add(
                    NodeExecutionRow(
                        run_id=run.id,
                        seq=seq,
                        node_id=n.node_id,
                        status=n.status,
                        input=n.input,
                        output=n.output,
                        logs=[x.model_dump() for x in n.logs],
                        error=n.error.model_dump() if n.error else None,
                        duration_ms=n.duration_ms,
                    )
                )
            s.flush()
            created = row.created_at
        return RunRecord(
            **run.model_dump(),
            workflow_id=workflow_id,
            version_no=version.version_no,
            input=run_input,
            created_at=created,
        )

    def get(self, run_id: str) -> RunRecord | None:
        with self.sf() as s:
            row = s.get(RunRow, run_id)
            if row is None:
                return None
            nodes = s.scalars(
                select(NodeExecutionRow)
                .where(NodeExecutionRow.run_id == run_id)
                .order_by(NodeExecutionRow.seq)
            ).all()
            return RunRecord(
                id=row.id,
                status=cast(RunStatus, row.status),
                duration_ms=row.duration_ms,
                workflow_id=row.workflow_id,
                version_no=row.version_no,
                input=row.input,
                created_at=row.created_at,
                nodes=[
                    NodeExecution(
                        node_id=n.node_id,
                        status=cast(NodeStatus, n.status),
                        input=n.input,
                        output=n.output,
                        logs=[LogLine(**x) for x in n.logs],
                        error=NodeError(**n.error) if n.error else None,
                        duration_ms=n.duration_ms,
                    )
                    for n in nodes
                ],
            )

    def list_for_workflow(self, workflow_id: str, limit: int = 50) -> list[RunSummary]:
        with self.sf() as s:
            rows = s.scalars(
                select(RunRow)
                .where(RunRow.workflow_id == workflow_id)
                .order_by(RunRow.created_at.desc())
                .limit(limit)
            ).all()
            return [
                RunSummary(
                    id=r.id,
                    status=r.status,
                    version_no=r.version_no,
                    duration_ms=r.duration_ms,
                    created_at=r.created_at,
                )
                for r in rows
            ]
