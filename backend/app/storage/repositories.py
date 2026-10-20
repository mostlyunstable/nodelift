import uuid
from typing import Any, cast

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.ports import LogLine, NodeError
from app.domain.records import (
    CredentialRecord,
    FileAnalysisRecord,
    RepoDiagnosticRecord,
    RepoEdgeRecord,
    RepoFileRecord,
    RepoPatchRecord,
    RepoReferenceRecord,
    RepoRevisionRecord,
    RepoSymbolRecord,
    RunRecord,
    RunSummary,
    VersionRecord,
    VersionSummary,
    WorkflowRecord,
    WorkflowSummary,
)
from app.domain.repositories import RevisionConflict
from app.domain.run import NodeExecution, NodeStatus, RunEvent, RunStatus
from app.domain.workflow import WorkflowDefinition
from app.storage.models import (
    CredentialRow,
    NodeExecutionRow,
    RepoDiagnosticRow,
    RepoEdgeRow,
    RepoFileRow,
    RepoPatchRow,
    RepoReferenceRow,
    RepoRevisionRow,
    RepoSymbolRow,
    RunEventRow,
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

    def create(
        self, run_id: str, workflow_id: str, version: VersionRecord, run_input: Any
    ) -> RunRecord:
        with self.sf.begin() as s:
            row = RunRow(
                id=run_id,
                workflow_id=workflow_id,
                version_id=version.id,
                version_no=version.version_no,
                status="running",
                input=run_input,
                duration_ms=0,
            )
            s.add(row)
            s.flush()
            return RunRecord(
                id=run_id,
                status="running",
                nodes=[],
                duration_ms=0,
                workflow_id=workflow_id,
                version_no=version.version_no,
                input=run_input,
                created_at=row.created_at,
            )

    def add_node_execution(self, run_id: str, seq: int, record: NodeExecution) -> None:
        with self.sf.begin() as s:
            s.add(
                NodeExecutionRow(
                    run_id=run_id,
                    seq=seq,
                    node_id=record.node_id,
                    status=record.status,
                    input=record.input,
                    output=record.output,
                    logs=[x.model_dump() for x in record.logs],
                    error=record.error.model_dump() if record.error else None,
                    duration_ms=record.duration_ms,
                    attempt=record.attempt,
                    reused=record.reused,
                    activated_ports=record.activated_ports,
                    skip_reason=record.skip_reason,
                )
            )

    def finish(self, run_id: str, status: RunStatus, duration_ms: int) -> None:
        with self.sf.begin() as s:
            row = s.get(RunRow, run_id)
            if row is not None:
                row.status, row.duration_ms = status, duration_ms

    def add_event(self, run_id: str, type: str, payload: dict[str, Any]) -> RunEvent:
        with self.sf.begin() as s:
            last = s.scalar(select(func.max(RunEventRow.seq)).where(RunEventRow.run_id == run_id))
            row = RunEventRow(run_id=run_id, seq=(last or 0) + 1, type=type, payload=payload)
            s.add(row)
            s.flush()
            return RunEvent(
                run_id=run_id,
                seq=row.seq,
                type=type,
                created_at=row.created_at,
                payload=payload,
            )

    def list_events(self, run_id: str, after_seq: int = 0, limit: int = 500) -> list[RunEvent]:
        with self.sf() as s:
            rows = s.scalars(
                select(RunEventRow)
                .where(RunEventRow.run_id == run_id, RunEventRow.seq > after_seq)
                .order_by(RunEventRow.seq)
                .limit(limit)
            ).all()
            return [
                RunEvent(
                    run_id=r.run_id,
                    seq=r.seq,
                    type=r.type,
                    created_at=r.created_at,
                    payload=r.payload,
                )
                for r in rows
            ]

    def prune_runs(self, workflow_id: str, keep: int) -> int:
        with self.sf.begin() as s:
            stale = s.scalars(
                select(RunRow.id)
                .where(RunRow.workflow_id == workflow_id, RunRow.status != "running")
                .order_by(RunRow.created_at.desc(), RunRow.id.desc())
                .offset(keep)
            ).all()
            if stale:
                s.execute(delete(RunRow).where(RunRow.id.in_(stale)))  # events/executions cascade
            return len(stale)

    def mark_stale_running(self) -> list[str]:
        with self.sf.begin() as s:
            rows = s.scalars(select(RunRow).where(RunRow.status == "running")).all()
            for r in rows:
                r.status = "failed"
            return [r.id for r in rows]

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
                        attempt=n.attempt,
                        reused=n.reused,
                        activated_ports=n.activated_ports,
                        skip_reason=n.skip_reason,
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


class SqlCredentialRepository:
    def __init__(self, sf: sessionmaker[Session]) -> None:
        self.sf = sf

    @staticmethod
    def _rec(r: CredentialRow) -> CredentialRecord:
        return CredentialRecord(
            id=r.id, name=r.name, kind=r.kind, description=r.description,
            created_at=r.created_at, updated_at=r.updated_at,
        )  # fmt: skip

    def list_all(self) -> list[CredentialRecord]:
        with self.sf() as s:
            return [
                self._rec(r) for r in s.scalars(select(CredentialRow).order_by(CredentialRow.name))
            ]

    def get(self, name: str) -> CredentialRecord | None:
        with self.sf() as s:
            row = s.scalars(select(CredentialRow).where(CredentialRow.name == name)).first()
            return self._rec(row) if row else None

    def create(self, name: str, kind: str, description: str) -> CredentialRecord:
        with self.sf.begin() as s:
            row = CredentialRow(
                id=f"cred_{uuid.uuid4().hex[:12]}", name=name, kind=kind, description=description
            )
            s.add(row)
            s.flush()
            return self._rec(row)

    def touch(self, name: str, description: str | None = None) -> CredentialRecord | None:
        with self.sf.begin() as s:
            row = s.scalars(select(CredentialRow).where(CredentialRow.name == name)).first()
            if row is None:
                return None
            row.updated_at = utcnow()
            if description is not None:
                row.description = description
            s.flush()
            return self._rec(row)

    def delete(self, name: str) -> bool:
        with self.sf.begin() as s:
            row = s.scalars(select(CredentialRow).where(CredentialRow.name == name)).first()
            if row is None:
                return False
            s.delete(row)
            return True


class SqlRepoRepository:
    def __init__(self, sf: sessionmaker[Session]) -> None:
        self.sf = sf

    @staticmethod
    def _rev(r: RepoRevisionRow) -> RepoRevisionRecord:
        return RepoRevisionRecord(
            schema_version=r.schema_version, id=r.id, owner=r.owner, repo=r.repo,
            full_name=r.full_name, branch=r.branch, default_branch=r.default_branch,
            commit_sha=r.commit_sha, description=r.description, status=r.status, phase=r.phase,
            file_count=r.file_count, text_count=r.text_count, binary_count=r.binary_count,
            skipped_count=r.skipped_count, total_bytes=r.total_bytes,
            analyzed_count=r.analyzed_count, analysis_status=r.analysis_status,
            analysis_error=r.analysis_error, edge_count=r.edge_count,
            diagnostic_count=r.diagnostic_count, error_code=r.error_code,
            error_message=r.error_message, created_at=r.created_at, updated_at=r.updated_at,
        )  # fmt: skip

    @staticmethod
    def _file(r: RepoFileRow) -> RepoFileRecord:
        return RepoFileRecord(
            path=r.path, language=r.language, size=r.size, lines=r.lines, binary=r.binary,
            stored=r.stored, skip_reason=r.skip_reason, analysis_status=r.analysis_status,
        )  # fmt: skip

    def create_revision(self, **fields: Any) -> RepoRevisionRecord:
        with self.sf.begin() as s:
            row = RepoRevisionRow(id=f"rev_{uuid.uuid4().hex[:12]}", **fields)
            s.add(row)
            s.flush()
            return self._rev(row)

    def get_revision(self, revision_id: str) -> RepoRevisionRecord | None:
        with self.sf() as s:
            row = s.get(RepoRevisionRow, revision_id)
            return self._rev(row) if row else None

    def find_revision(self, owner: str, repo: str, sha: str) -> RepoRevisionRecord | None:
        with self.sf() as s:
            row = s.scalars(
                select(RepoRevisionRow).where(
                    RepoRevisionRow.owner == owner,
                    RepoRevisionRow.repo == repo,
                    RepoRevisionRow.commit_sha == sha,
                )
            ).first()
            return self._rev(row) if row else None

    def list_revisions(self) -> list[RepoRevisionRecord]:
        with self.sf() as s:
            rows = s.scalars(select(RepoRevisionRow).order_by(RepoRevisionRow.created_at.desc()))
            return [self._rev(r) for r in rows]

    def update_revision(self, revision_id: str, **fields: Any) -> RepoRevisionRecord | None:
        with self.sf.begin() as s:
            row = s.get(RepoRevisionRow, revision_id)
            if row is None:
                return None
            for k, v in fields.items():
                setattr(row, k, v)
            row.updated_at = utcnow()
            s.flush()
            return self._rev(row)

    def add_files(self, revision_id: str, files: list[RepoFileRecord]) -> None:
        with self.sf.begin() as s:
            s.add_all(RepoFileRow(revision_id=revision_id, **f.model_dump()) for f in files)

    def list_files(self, revision_id: str) -> list[RepoFileRecord]:
        with self.sf() as s:
            rows = s.scalars(
                select(RepoFileRow)
                .where(RepoFileRow.revision_id == revision_id)
                .order_by(RepoFileRow.path)
            )
            return [self._file(r) for r in rows]

    def get_file(self, revision_id: str, path: str) -> RepoFileRecord | None:
        with self.sf() as s:
            row = s.scalars(
                select(RepoFileRow).where(
                    RepoFileRow.revision_id == revision_id, RepoFileRow.path == path
                )
            ).first()
            return self._file(row) if row else None

    def delete_revision(self, revision_id: str) -> bool:
        with self.sf.begin() as s:
            for table in (
                RepoEdgeRow,
                RepoSymbolRow,
                RepoDiagnosticRow,
                RepoReferenceRow,
                RepoFileRow,
                RepoPatchRow,
            ):
                s.execute(delete(table).where(table.revision_id == revision_id))
            row = s.get(RepoRevisionRow, revision_id)
            if row is None:
                return False
            s.delete(row)
            return True

    def fail_stale_imports(self) -> int:
        """Imports left running by a crash can never finish; mark them failed."""
        with self.sf.begin() as s:
            rows = list(
                s.scalars(select(RepoRevisionRow).where(RepoRevisionRow.status == "importing"))
            )
            for r in rows:
                r.status = "failed"
                r.error_code = "server_restarted"
                r.error_message = "Nodecraft was closed before the import finished."
                r.phase = "Failed"
                r.updated_at = utcnow()
            for r in s.scalars(
                select(RepoRevisionRow).where(RepoRevisionRow.analysis_status == "analyzing")
            ):
                r.analysis_status = "failed"
                r.analysis_error = "Nodecraft was closed before the analysis finished."
                r.updated_at = utcnow()
            return len(rows)

    # -- analysis ---------------------------------------------------------------------------
    def replace_analysis(
        self,
        revision_id: str,
        edges: list[RepoEdgeRecord],
        symbols: list[RepoSymbolRecord],
        diagnostics: list[RepoDiagnosticRecord],
        statuses: dict[str, str],
        status: str,
        references: list[RepoReferenceRecord] | None = None,
    ) -> None:
        with self.sf.begin() as s:
            for table in (RepoEdgeRow, RepoSymbolRow, RepoDiagnosticRow, RepoReferenceRow):
                s.execute(delete(table).where(table.revision_id == revision_id))
            s.add_all(RepoEdgeRow(revision_id=revision_id, **e.model_dump()) for e in edges)
            s.add_all(RepoSymbolRow(revision_id=revision_id, **x.model_dump()) for x in symbols)
            s.add_all(
                RepoDiagnosticRow(revision_id=revision_id, **d.model_dump()) for d in diagnostics
            )
            s.add_all(
                RepoReferenceRow(revision_id=revision_id, **r.model_dump())
                for r in references or []
            )
            for f in s.scalars(select(RepoFileRow).where(RepoFileRow.revision_id == revision_id)):
                f.analysis_status = statuses.get(f.path, "not_analyzed")
            rev = s.get(RepoRevisionRow, revision_id)
            if rev is not None:
                rev.analysis_status = status
                rev.analysis_error = None
                rev.analyzed_count = sum(1 for v in statuses.values() if v == "analyzed")
                rev.edge_count = len(edges)
                rev.diagnostic_count = sum(
                    1 for d in diagnostics if d.severity != "info"
                )  # notes are not problems
                rev.updated_at = utcnow()

    @staticmethod
    def _edge(r: RepoEdgeRow) -> RepoEdgeRecord:
        return RepoEdgeRecord(
            src=r.src, dst=r.dst, kind=r.kind, confidence=r.confidence, line=r.line, raw=r.raw,
            provenance=r.provenance, note=r.note,
        )  # fmt: skip

    @staticmethod
    def _ref(r: RepoReferenceRow) -> RepoReferenceRecord:
        return RepoReferenceRecord(
            path=r.path, line=r.line, column=r.column, end_column=r.end_column, name=r.name,
            kind=r.kind, scope=r.scope, dst_path=r.dst_path, dst_symbol=r.dst_symbol,
            dst_line=r.dst_line, confidence=r.confidence, provenance=r.provenance, note=r.note,
        )  # fmt: skip

    @staticmethod
    def _diag(r: RepoDiagnosticRow) -> RepoDiagnosticRecord:
        return RepoDiagnosticRecord(
            path=r.path, line=r.line, column=r.column, severity=r.severity, code=r.code,
            message=r.message, source=r.source,
        )  # fmt: skip

    def list_internal_edges(
        self, revision_id: str, limit: int
    ) -> tuple[list[RepoEdgeRecord], bool]:
        with self.sf() as s:
            rows = list(
                s.scalars(
                    select(RepoEdgeRow)
                    .where(RepoEdgeRow.revision_id == revision_id, RepoEdgeRow.dst.is_not(None))
                    .order_by(RepoEdgeRow.id)
                    .limit(limit + 1)
                )
            )
            return [self._edge(r) for r in rows[:limit]], len(rows) > limit

    def list_diagnostics(self, revision_id: str, limit: int) -> list[RepoDiagnosticRecord]:
        with self.sf() as s:
            rows = s.scalars(
                select(RepoDiagnosticRow)
                .where(RepoDiagnosticRow.revision_id == revision_id)
                .order_by(RepoDiagnosticRow.path, RepoDiagnosticRow.line)
                .limit(limit)
            )
            return [self._diag(r) for r in rows]

    def file_analysis(self, revision_id: str, path: str) -> FileAnalysisRecord | None:
        with self.sf() as s:
            f = s.scalars(
                select(RepoFileRow).where(
                    RepoFileRow.revision_id == revision_id, RepoFileRow.path == path
                )
            ).first()
            if f is None:
                return None
            syms = s.scalars(
                select(RepoSymbolRow)
                .where(RepoSymbolRow.revision_id == revision_id, RepoSymbolRow.path == path)
                .order_by(RepoSymbolRow.line)
            )
            out = s.scalars(
                select(RepoEdgeRow)
                .where(RepoEdgeRow.revision_id == revision_id, RepoEdgeRow.src == path)
                .order_by(RepoEdgeRow.line)
            )
            inc = s.scalars(
                select(RepoEdgeRow)
                .where(RepoEdgeRow.revision_id == revision_id, RepoEdgeRow.dst == path)
                .order_by(RepoEdgeRow.src, RepoEdgeRow.line)
            )
            refs = s.scalars(
                select(RepoReferenceRow)
                .where(RepoReferenceRow.revision_id == revision_id, RepoReferenceRow.path == path)
                .order_by(RepoReferenceRow.line, RepoReferenceRow.column)
            )
            called = s.scalars(
                select(RepoReferenceRow)
                .where(
                    RepoReferenceRow.revision_id == revision_id,
                    RepoReferenceRow.dst_path == path,
                    RepoReferenceRow.path != path,
                )
                .order_by(RepoReferenceRow.path, RepoReferenceRow.line)
                .limit(300)
            )
            diags = s.scalars(
                select(RepoDiagnosticRow)
                .where(RepoDiagnosticRow.revision_id == revision_id, RepoDiagnosticRow.path == path)
                .order_by(RepoDiagnosticRow.line)
            )
            return FileAnalysisRecord(
                path=path,
                status=f.analysis_status,
                symbols=[
                    RepoSymbolRecord(
                        path=x.path, name=x.name, kind=x.kind, line=x.line, end_line=x.end_line,
                        parent=x.parent, exported=x.exported,
                    )
                    for x in syms
                ],
                references=[self._ref(r) for r in refs],
                called_by=[self._ref(r) for r in called],
                imports=[self._edge(r) for r in out],
                dependents=[self._edge(r) for r in inc],
                diagnostics=[self._diag(r) for r in diags],
            )  # fmt: skip

    # -- patches ----------------------------------------------------------------------------
    @staticmethod
    def _patch(r: RepoPatchRow) -> RepoPatchRecord:
        return RepoPatchRecord(
            id=r.id, revision_id=r.revision_id, path=r.path, title=r.title, additions=r.additions,
            deletions=r.deletions, applied=r.applied, created_at=r.created_at,
            applied_at=r.applied_at,
        )  # fmt: skip

    def create_patch(
        self,
        revision_id: str,
        path: str,
        title: str,
        new_content: str,
        additions: int,
        deletions: int,
    ) -> RepoPatchRecord:
        with self.sf.begin() as s:
            row = RepoPatchRow(
                id=f"patch_{uuid.uuid4().hex[:12]}", revision_id=revision_id, path=path,
                title=title, new_content=new_content, additions=additions, deletions=deletions,
            )  # fmt: skip
            s.add(row)
            s.flush()
            return self._patch(row)

    def list_patches(self, revision_id: str) -> list[RepoPatchRecord]:
        with self.sf() as s:
            rows = s.scalars(
                select(RepoPatchRow)
                .where(RepoPatchRow.revision_id == revision_id)
                .order_by(RepoPatchRow.created_at)
            )
            return [self._patch(r) for r in rows]

    def get_patch(self, patch_id: str) -> tuple[RepoPatchRecord, str] | None:
        with self.sf() as s:
            row = s.get(RepoPatchRow, patch_id)
            return (self._patch(row), row.new_content) if row else None

    def set_patch_applied(self, patch_id: str, applied: bool) -> None:
        with self.sf.begin() as s:
            row = s.get(RepoPatchRow, patch_id)
            if row is not None:
                row.applied = applied
                row.applied_at = utcnow() if applied else None

    def delete_patch(self, patch_id: str) -> bool:
        with self.sf.begin() as s:
            row = s.get(RepoPatchRow, patch_id)
            if row is None:
                return False
            s.delete(row)
            return True
