# ruff: noqa: E501
import posixpath
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.domain.records import (
    RepoDiagnosticRecord,
    RepoEdgeRecord,
    RepoFileRecord,
    RepoReferenceRecord,
    RepoSymbolRecord,
)
from app.explorer.analysis.base import Analyzer, FileAnalysis
from app.explorer.analysis.calls import resolve_calls
from app.explorer.analysis.registry import default_analyzers
from app.explorer.analysis.resolve import Resolver
from app.explorer.archive import Cancelled


@dataclass
class AnalysisResult:
    edges: list[RepoEdgeRecord] = field(default_factory=list)
    symbols: list[RepoSymbolRecord] = field(default_factory=list)
    diagnostics: list[RepoDiagnosticRecord] = field(default_factory=list)
    references: list[RepoReferenceRecord] = field(default_factory=list)
    statuses: dict[str, str] = field(
        default_factory=dict
    )  # path -> analyzed|failed|unsupported|skipped|timeout
    partial: bool = False


_ARTIFACT_DIRS = {
    "node_modules",
    "dist",
    "build",
    "out",
    "lib-cov",
    "coverage",
    ".next",
    ".nuxt",
    "target",
    "generated",
    "__generated__",
    "vendor",
    "native",
}


def _is_artifact_path(spec: str) -> bool:
    """An import of build output or installed packages: absent from a source checkout by design."""
    return any(part in _ARTIFACT_DIRS for part in spec.replace("\\", "/").split("/"))


def _test_targets(path: str, files: set[str], language: str) -> list[str]:
    """Files a test file is named after (test_foo.py -> foo.py). A guess, reported as one."""
    name = posixpath.basename(path)
    stem, ext = posixpath.splitext(name)
    if language == "python":
        if stem.startswith("test_"):
            want = stem[5:]
        elif stem.endswith("_test"):
            want = stem[:-5]
        else:
            return []
        wanted = {f"{want}{ext}"}
    else:
        for marker in (".test", ".spec"):
            if stem.endswith(marker):
                want = stem[: -len(marker)]
                wanted = {f"{want}{e}" for e in (".ts", ".tsx", ".js", ".jsx", ".mjs")}
                break
        else:
            return []
    hits = [
        p
        for p in files
        if posixpath.basename(p) in wanted
        and p != path
        and "test" not in posixpath.basename(p).lower()
    ]
    if len(hits) > 3:  # too ambiguous to say anything useful
        return []
    return sorted(hits)


def analyze_files(
    root: Path,
    files: list[RepoFileRecord],
    cancel: threading.Event | None = None,
    budget_seconds: float = 120.0,
    analyzers: dict[str, Analyzer] | None = None,
) -> AnalysisResult:
    """Analyse every readable file of a supported language. Reads text only; executes nothing."""
    analyzers = analyzers if analyzers is not None else default_analyzers()
    paths = {f.path for f in files}
    go_modules: dict[str, str] = {}
    for p in paths:
        if p.endswith("go.mod"):
            try:
                for line in (root.resolve() / p).read_text(encoding="utf-8").splitlines():
                    if line.startswith("module "):
                        go_modules[posixpath.dirname(p)] = line.split(None, 1)[1].strip().strip('"')
                        break
            except OSError:
                pass
    resolver = Resolver(paths, go_modules)
    table_refs: list[tuple[str, int, str]] = []
    res = AnalysisResult()
    deadline = time.monotonic() + budget_seconds
    lang_of = {f.path: f.language for f in files}
    analyses: dict[str, FileAnalysis] = {}
    providers: dict[str, str] = {}
    base = root.resolve()
    for f in files:
        if cancel is not None and cancel.is_set():
            raise Cancelled
        an = analyzers.get(f.language)
        if not f.stored:
            res.statuses[f.path] = "skipped"
            continue
        if an is None:
            res.statuses[f.path] = "unsupported"
            continue
        if time.monotonic() > deadline:
            res.statuses[f.path] = "timeout"
            res.partial = True
            continue
        try:
            target = (base / f.path).resolve()
            if base not in target.parents:
                res.statuses[f.path] = "failed"
                continue
            result = an.analyze(f.path, target.read_text(encoding="utf-8"))
        except Exception as e:  # one bad file must not stop the run
            res.statuses[f.path] = "failed"
            res.diagnostics.append(
                RepoDiagnosticRecord(
                    path=f.path, line=1, column=0, severity="warning", code="analysis_failed",
                    message=f"Analysis failed ({type(e).__name__})", source=an.id,
                )
            )  # fmt: skip
            continue
        res.statuses[f.path] = "analyzed"
        analyses[f.path] = result
        providers[f.path] = an.id
        res.symbols.extend(result.symbols)
        res.diagnostics.extend(result.diagnostics)
        seen: set[tuple[str, str | None, str, int, str]] = set()
        for ref in result.refs:
            if ref.kind == "table":  # SQL: matched to CREATE statements once every file is read
                table_refs.append((f.path, ref.line, ref.raw))
                continue
            for edge in resolver.resolve(f.path, f.language, ref, an.id):
                key = (edge.src, edge.dst, edge.kind, edge.line, edge.raw)
                if key in seen:
                    continue
                seen.add(key)
                res.edges.append(edge)
                if (
                    edge.confidence == "unresolved"
                    and edge.dst is None
                    and edge.kind == "import"
                    and "relative" in (edge.note or "")
                ):
                    if not _is_artifact_path(edge.raw):
                        res.diagnostics.append(
                            RepoDiagnosticRecord(
                                path=f.path, line=edge.line, column=0,
                                severity="warning" if f.language == "python" else "info",
                                code="unresolved_import",
                                message=f"Cannot find {edge.raw or 'this module'} in the repository", source=an.id,
                            )
                        )  # fmt: skip

    creators: dict[str, list[str]] = {}
    for sy in res.symbols:
        if lang_of.get(sy.path) == "sql" and sy.kind == "class":
            creators.setdefault(sy.name.lower(), []).append(sy.path)
    for tpath, tline, tname in table_refs:
        owners = [o for o in creators.get(tname.lower(), []) if o != tpath]
        if len(owners) == 1:
            res.edges.append(
                RepoEdgeRecord(
                    src=tpath, dst=owners[0], kind="reference", confidence="heuristic", line=tline, raw=tname,
                    provenance="sqlglot", note="table name matched to its CREATE statement; no schema or search path is considered",
                )
            )  # fmt: skip
    res.references = resolve_calls(analyses, lang_of, providers, resolver)

    # name-based test association, only where no import already links the pair
    linked = {(e.src, e.dst) for e in res.edges if e.dst}
    for f in files:
        if res.statuses.get(f.path) != "analyzed":
            continue
        for tgt in _test_targets(f.path, paths, lang_of[f.path]):
            if (f.path, tgt) not in linked:
                res.edges.append(
                    RepoEdgeRecord(
                        src=f.path, dst=tgt, kind="tests", confidence="heuristic", line=1, raw=tgt,
                        provenance="naming convention",
                        note="matched by file name only; the test does not import it",
                    )
                )  # fmt: skip
    return res
