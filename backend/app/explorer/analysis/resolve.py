# ruff: noqa: E501
"""Resolve references to files of the repository. Anything not provably in the repo is not guessed."""

import posixpath
import sys

from app.domain.records import RepoEdgeRecord
from app.explorer.analysis.base import Ref

JS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json", ".d.ts")
JS_INDEX = tuple(f"index{e}" for e in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"))
_ALIAS_PREFIXES = (
    "@/",
    "~/",
    "#",
    "$lib/",
    "src/",
)  # tsconfig/bundler aliases; configs are not applied
_NODE_BUILTINS = {
    "fs", "path", "os", "http", "https", "url", "util", "events", "stream", "crypto", "child_process",
    "assert", "buffer", "zlib", "net", "tls", "dns", "readline", "process", "querystring", "module",
}  # fmt: skip


def _edge(
    src: str, dst: str | None, ref: Ref, confidence: str, provenance: str, note: str | None = None
) -> RepoEdgeRecord:
    n = note if note is not None else ref.note
    if note is not None and ref.note:
        n = f"{note}; {ref.note}"
    return RepoEdgeRecord(
        src=src, dst=dst, kind=ref.kind, confidence=confidence, line=ref.line, raw=ref.raw,
        provenance=provenance, note=n,
    )  # fmt: skip


class Resolver:
    def __init__(self, files: set[str]) -> None:
        self.files = files

    # ---- Python -------------------------------------------------------------------------
    def _py_root(self, path: str) -> str:
        d = posixpath.dirname(path)
        while d and f"{d}/__init__.py" in self.files:
            d = posixpath.dirname(d)
        return d

    def _py_module_file(self, root: str, dotted: str) -> str | None:
        base = posixpath.join(root, *dotted.split(".")) if dotted else root
        for cand in (f"{base}.py", f"{base}/__init__.py"):
            cand = cand.lstrip("/")
            if cand in self.files:
                return cand
        return None

    def _py_search(self, src: str, dotted: str) -> str | None:
        """Mirror sys.path order: the importer's folder, its package root, the repo root, src/, lib/."""
        roots: list[str] = []
        for r in (posixpath.dirname(src), self._py_root(src), "", "src", "lib"):
            if r not in roots:
                roots.append(r)
        for r in roots:
            hit = self._py_module_file(r, dotted)
            if hit and hit != src:
                return hit
        return None

    def python(self, src: str, ref: Ref, provenance: str) -> list[RepoEdgeRecord]:
        if ref.dynamic:
            return [
                _edge(
                    src,
                    None,
                    ref,
                    "unresolved",
                    provenance,
                    "dynamic import: not resolvable statically",
                )
            ]
        out: list[RepoEdgeRecord] = []
        if ref.level > 0:
            base = posixpath.dirname(src)
            for _ in range(ref.level - 1):
                base = posixpath.dirname(base)
            target = (
                self._py_module_file(base, ref.raw) if ref.raw else self._py_module_file(base, "")
            )
            if ref.raw == "" and f"{base}/__init__.py".lstrip("/") in self.files:
                target = f"{base}/__init__.py".lstrip("/")
            for name in ref.names:
                sub = self._py_module_file(base, f"{ref.raw}.{name}" if ref.raw else name)
                if sub and sub != src:
                    out.append(_edge(src, sub, ref, "resolved", provenance))
            if target and target != src and not any(e.dst == target for e in out):
                out.append(_edge(src, target, ref, "resolved", provenance))
            if not out:
                out.append(
                    _edge(
                        src,
                        None,
                        ref,
                        "unresolved",
                        provenance,
                        "relative import target not found in the repository",
                    )
                )
            return out
        target = self._py_search(src, ref.raw)
        if target is None:
            top = ref.raw.split(".")[0]
            if top in sys.stdlib_module_names:
                return [_edge(src, None, ref, "external", provenance, "standard library")]
            return [
                _edge(
                    src,
                    None,
                    ref,
                    "external",
                    provenance,
                    "not found in the repository (third-party or generated)",
                )
            ]
        for name in ref.names:
            if name == "*":
                continue
            sub = self._py_search(src, f"{ref.raw}.{name}")
            if sub and sub != target:
                out.append(_edge(src, sub, ref, "resolved", provenance))
        out.append(_edge(src, target, ref, "resolved", provenance))
        return out

    # ---- JavaScript / TypeScript ----------------------------------------------------------
    def _js_candidates(self, base: str) -> list[str]:
        cands = [base]
        stem, ext = posixpath.splitext(base)
        swap = {".js": (".ts", ".tsx"), ".jsx": (".tsx",), ".mjs": (".mts",), ".cjs": (".cts",)}
        for e in swap.get(ext, ()):
            cands.append(stem + e)
        cands += [base + e for e in JS_EXTS]
        cands += [posixpath.join(base, i) for i in JS_INDEX]
        return cands

    def javascript(self, src: str, ref: Ref, provenance: str) -> list[RepoEdgeRecord]:
        spec = ref.raw
        if ref.dynamic:
            return [
                _edge(
                    src,
                    None,
                    ref,
                    "unresolved",
                    provenance,
                    "dynamic import: not resolvable statically",
                )
            ]
        if spec.startswith(("./", "../")) or spec in {".", ".."}:
            base = posixpath.normpath(posixpath.join(posixpath.dirname(src), spec))
            if base.startswith(".."):
                return [
                    _edge(src, None, ref, "unresolved", provenance, "points outside the repository")
                ]
            for c in self._js_candidates(base):
                if c in self.files and c != src:
                    return [_edge(src, c, ref, "resolved", provenance)]
            return [
                _edge(src, None, ref, "unresolved", provenance, "relative import target not found")
            ]
        if spec.startswith("node:") or spec in _NODE_BUILTINS:
            return [_edge(src, None, ref, "external", provenance, "Node.js built-in")]
        if spec.startswith(_ALIAS_PREFIXES) and not spec.startswith("src/"):
            return [
                _edge(
                    src,
                    None,
                    ref,
                    "unresolved",
                    provenance,
                    "path alias (tsconfig/bundler config is not applied)",
                )
            ]
        if spec.startswith("/"):
            return [_edge(src, None, ref, "unresolved", provenance, "absolute path")]
        return [
            _edge(
                src, None, ref, "external", provenance, "package dependency (not in the repository)"
            )
        ]

    # ---- HTML / CSS ------------------------------------------------------------------------
    def web(self, src: str, ref: Ref, provenance: str) -> list[RepoEdgeRecord]:
        raw = ref.raw.strip()
        if not raw or raw.startswith(("data:", "#", "mailto:", "javascript:")):
            return []
        if "://" in raw or raw.startswith("//"):
            return [_edge(src, None, ref, "external", provenance, "remote URL")]
        path = raw.split("#", 1)[0].split("?", 1)[0]
        if not path:
            return []
        base = (
            posixpath.normpath(path.lstrip("/"))
            if path.startswith("/")
            else posixpath.normpath(posixpath.join(posixpath.dirname(src), path))
        )
        if base.startswith(".."):
            return [
                _edge(src, None, ref, "unresolved", provenance, "points outside the repository")
            ]
        if base in self.files and base != src:
            conf = "heuristic" if path.startswith("/") else "resolved"
            note = (
                "site-root path resolved from the repository root" if path.startswith("/") else None
            )
            return [_edge(src, base, ref, conf, provenance, note)]
        return [_edge(src, None, ref, "unresolved", provenance, "file not found in the repository")]

    def resolve(self, src: str, language: str, ref: Ref, provenance: str) -> list[RepoEdgeRecord]:
        if language == "python":
            return self.python(src, ref, provenance)
        if language in {"javascript", "typescript"}:
            return self.javascript(src, ref, provenance)
        return self.web(src, ref, provenance)
