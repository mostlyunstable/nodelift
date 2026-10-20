"""Import GitHub repositories at a pinned commit and serve their indexed files.

Imports run as background tasks and report progress through the revision row. Repository code is
never executed; files are only read, indexed and (when small UTF-8 text) cached on disk.
"""

import asyncio
import contextlib
import logging
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from pydantic import BaseModel

from app.config import Settings
from app.domain.errors import AppError
from app.domain.records import (
    FileAnalysisRecord,
    RepoFileRecord,
    RepoGraphRecord,
    RepoRevisionRecord,
)
from app.domain.repositories import RepoRepository
from app.explorer.analysis.runner import analyze_files
from app.explorer.archive import Cancelled, ExtractedFile, Limits, extract_tarball
from app.explorer.github import GitHubClient
from app.explorer.urls import InvalidRepoUrl, parse_github_url

log = logging.getLogger("nodecraft.explorer")


@dataclass
class ImportJobs:
    """Live import tasks. Owned by the application, shared by every request."""

    tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    cancels: dict[str, threading.Event] = field(default_factory=dict)
    sem: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(2))

    async def shutdown(self) -> None:
        for ev in self.cancels.values():
            ev.set()
        if self.tasks:
            await asyncio.wait(list(self.tasks.values()), timeout=5)


class FileContent(BaseModel):
    path: str
    language: str
    size: int
    lines: int
    binary: bool
    content: str | None
    reason: str | None  # why content is unavailable


class ExplorerService:
    def __init__(
        self,
        repo: RepoRepository,
        settings: Settings,
        jobs: ImportJobs,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.repo = repo
        self.jobs = jobs
        self.transport = transport
        self.root = settings.data_dir / "repos"
        self.limits = Limits(
            max_files=settings.explorer_max_files,
            max_file_bytes=settings.explorer_max_file_kb * 1024,
            max_total_bytes=settings.explorer_max_total_mb * 1024 * 1024,
        )
        self.max_download = settings.explorer_max_download_mb * 1024 * 1024
        self.analysis_seconds = settings.explorer_analysis_seconds
        self.max_graph_edges = settings.explorer_max_graph_edges

    # -- paths ------------------------------------------------------------------------------
    def _dir(self, revision_id: str) -> Path:
        return self.root / revision_id

    def _remove_dir(self, revision_id: str) -> None:
        shutil.rmtree(self._dir(revision_id), ignore_errors=True)

    # -- import -----------------------------------------------------------------------------
    async def start_import(self, url: str) -> tuple[RepoRevisionRecord, bool]:
        """Resolve the URL to a commit, then import it in the background.

        Returns (revision, started). `started` is False when this exact commit is already imported
        or importing, so the same graph is never built twice.
        """
        try:
            ref = parse_github_url(url)
        except InvalidRepoUrl as e:
            raise AppError(422, "invalid_repo_url", str(e)) from e
        async with GitHubClient(self.transport) as gh:
            resolved = await gh.resolve(ref)
        owner, name = ref.owner.lower(), ref.repo.lower()
        existing = self.repo.find_revision(owner, name, resolved.commit_sha)
        if existing is not None:
            if existing.status in ("ready", "importing"):
                return existing, False
            self.repo.delete_revision(existing.id)  # failed/cancelled: start clean
            self._remove_dir(existing.id)
        try:
            rev = self.repo.create_revision(
                owner=owner, repo=name, full_name=resolved.full_name, branch=resolved.branch,
                default_branch=resolved.default_branch, commit_sha=resolved.commit_sha,
                description=resolved.description, status="importing", phase="Queued",
            )  # fmt: skip
        except Exception:
            again = self.repo.find_revision(owner, name, resolved.commit_sha)
            if again is None:
                raise
            return again, False
        cancel = threading.Event()
        self.jobs.cancels[rev.id] = cancel
        task = asyncio.create_task(self._run(rev, cancel))
        self.jobs.tasks[rev.id] = task
        task.add_done_callback(lambda _t, rid=rev.id: self._forget(rid))  # type: ignore[misc]
        return rev, True

    def _forget(self, revision_id: str) -> None:
        self.jobs.tasks.pop(revision_id, None)
        self.jobs.cancels.pop(revision_id, None)

    async def _run(self, rev: RepoRevisionRecord, cancel: threading.Event) -> None:
        rid = rev.id
        archive = self._dir(rid) / "archive.tgz"
        try:
            async with self.jobs.sem:
                self.repo.update_revision(rid, phase="Downloading from GitHub")
                archive.parent.mkdir(parents=True, exist_ok=True)
                async with GitHubClient(self.transport) as gh:
                    size = await gh.download_tarball(
                        rev.owner, rev.repo, rev.commit_sha, archive, self.max_download, cancel
                    )
                self.repo.update_revision(
                    rid, phase="Extracting and indexing files", total_bytes=size
                )
                files = await asyncio.to_thread(
                    extract_tarball,
                    archive,
                    self._dir(rid) / "files",
                    self.limits,
                    cancel,
                    lambda n: self._progress(rid, n),
                )
            self._finish(rid, files)
            await self._analyze(rid, cancel)
        except Cancelled:
            self.repo.update_revision(rid, status="cancelled", phase="Cancelled")
            self._remove_dir(rid)
        except AppError as e:
            self.repo.update_revision(
                rid, status="failed", phase="Failed", error_code=e.code, error_message=e.message
            )
            self._remove_dir(rid)
        except Exception:
            log.exception("repository import failed")
            self.repo.update_revision(
                rid, status="failed", phase="Failed", error_code="internal_error",
                error_message="The import failed unexpectedly. See the application log.",
            )  # fmt: skip
            self._remove_dir(rid)
        finally:
            with contextlib.suppress(OSError):
                archive.unlink()

    def _progress(self, rid: str, n: int) -> None:
        self.repo.update_revision(rid, file_count=n)

    def _finish(self, rid: str, files: list[ExtractedFile]) -> None:
        records = [
            RepoFileRecord(
                path=f.path, language=f.language, size=f.size, lines=f.lines, binary=f.binary,
                stored=f.stored, skip_reason=f.skip_reason, analysis_status="not_analyzed",
            )
            for f in files
        ]  # fmt: skip
        self.repo.add_files(rid, records)
        self.repo.update_revision(
            rid, status="ready", phase="Ready", file_count=len(records),
            text_count=sum(1 for f in files if f.stored),
            binary_count=sum(1 for f in files if f.binary),
            skipped_count=sum(1 for f in files if f.skip_reason == "too_large"),
        )  # fmt: skip

    async def _analyze(self, rid: str, cancel: threading.Event) -> None:
        """Static analysis of the cached files. Failure here never makes the import itself fail."""
        self.repo.update_revision(rid, analysis_status="analyzing", analysis_error=None)
        try:
            files = self.repo.list_files(rid)
            res = await asyncio.to_thread(
                analyze_files, self._dir(rid) / "files", files, cancel, float(self.analysis_seconds)
            )
            self.repo.replace_analysis(
                rid, res.edges, res.symbols, res.diagnostics, res.statuses,
                "partial" if res.partial else "done",
            )  # fmt: skip
        except Cancelled:
            self.repo.update_revision(rid, analysis_status="cancelled")
        except Exception:
            log.exception("repository analysis failed")
            self.repo.update_revision(
                rid, analysis_status="failed",
                analysis_error="The analysis failed unexpectedly. See the application log.",
            )  # fmt: skip

    def analyze(self, revision_id: str) -> RepoRevisionRecord:
        """(Re)run analysis in the background, e.g. for a revision imported before analysis."""
        rev = self._ready(revision_id)
        if rev.analysis_status == "analyzing" or revision_id in self.jobs.tasks:
            return rev
        cancel = threading.Event()
        self.jobs.cancels[revision_id] = cancel
        self.repo.update_revision(revision_id, analysis_status="analyzing", analysis_error=None)
        task = asyncio.create_task(self._analyze(revision_id, cancel))
        self.jobs.tasks[revision_id] = task
        task.add_done_callback(lambda _t, rid=revision_id: self._forget(rid))  # type: ignore[misc]
        return self.get(revision_id)

    def graph(self, revision_id: str) -> RepoGraphRecord:
        self._ready(revision_id)
        edges, truncated = self.repo.list_internal_edges(revision_id, self.max_graph_edges)
        return RepoGraphRecord(
            edges=edges,
            truncated=truncated,
            diagnostics=self.repo.list_diagnostics(revision_id, 5000),
        )

    def file_analysis(self, revision_id: str, path: str) -> FileAnalysisRecord:
        self._ready(revision_id)
        out = self.repo.file_analysis(revision_id, path)
        if out is None:
            raise AppError(404, "file_not_found", "That file is not in this revision")
        return out

    def cancel(self, revision_id: str) -> RepoRevisionRecord:
        rev = self.get(revision_id)
        ev = self.jobs.cancels.get(revision_id)
        if ev is not None:
            ev.set()  # the import notices at its next chunk/file and records the cancellation
        return rev

    # -- reads ------------------------------------------------------------------------------
    def get(self, revision_id: str) -> RepoRevisionRecord:
        rev = self.repo.get_revision(revision_id)
        if rev is None:
            raise AppError(404, "not_found", "Repository revision not found")
        return rev

    def list_revisions(self) -> list[RepoRevisionRecord]:
        return self.repo.list_revisions()

    def files(self, revision_id: str) -> list[RepoFileRecord]:
        self._ready(revision_id)
        return self.repo.list_files(revision_id)

    def _ready(self, revision_id: str) -> RepoRevisionRecord:
        rev = self.get(revision_id)
        if rev.status != "ready":
            raise AppError(409, "revision_not_ready", f"The import is {rev.status}")
        return rev

    def read_file(self, revision_id: str, path: str) -> FileContent:
        self._ready(revision_id)
        meta = self.repo.get_file(revision_id, path)  # only indexed paths can be read
        if meta is None:
            raise AppError(404, "file_not_found", "That file is not in this revision")
        base = FileContent(
            path=meta.path, language=meta.language, size=meta.size, lines=meta.lines,
            binary=meta.binary, content=None, reason=meta.skip_reason,
        )  # fmt: skip
        if not meta.stored:
            return base
        root = (self._dir(revision_id) / "files").resolve()
        target = (root / meta.path).resolve()
        try:
            if root not in target.parents:
                raise OSError("outside the repository folder")
            base.content = target.read_text(encoding="utf-8")
        except OSError:
            base.reason = "cache_missing"
        return base

    def delete(self, revision_id: str) -> None:
        rev = self.get(revision_id)
        if rev.status == "importing":
            raise AppError(409, "import_running", "Cancel the import before deleting it")
        self.repo.delete_revision(revision_id)
        self._remove_dir(revision_id)
