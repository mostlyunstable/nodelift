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


_GO_STD_FIRST_SEGMENT_NO_DOT = True  # Go standard library paths have no dot in their first segment


class Resolver:
    def __init__(self, files: set[str], go_modules: dict[str, str] | None = None) -> None:
        self.files = files
        self.go_modules = go_modules or {}  # folder of go.mod -> module path
        self._java: list[str] | None = None

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

    def python_module(self, src: str, raw: str, level: int) -> str | None:
        """The file an import of `raw` (with `level` leading dots) refers to, if it is in the repository."""
        if level > 0:
            base = posixpath.dirname(src)
            for _ in range(level - 1):
                base = posixpath.dirname(base)
            hit = self._py_module_file(base, raw)
            if raw == "" and f"{base}/__init__.py".lstrip("/") in self.files:
                hit = f"{base}/__init__.py".lstrip("/")
            return hit if hit != src else None
        return self._py_search(src, raw) if raw else None

    def js_module(self, src: str, raw: str) -> str | None:
        edges = self.javascript(src, Ref(raw, "import", 1), "calls")
        return next((e.dst for e in edges if e.dst), None)

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
        if (
            ref.note == "uses:"
        ):  # GitHub Actions: a local action is a folder, relative to the repository root
            root_rel = posixpath.normpath(path)
            for cand in (root_rel, f"{root_rel}/action.yml", f"{root_rel}/action.yaml"):
                if cand in self.files and cand != src:
                    return [
                        _edge(
                            src,
                            cand,
                            ref,
                            "resolved",
                            provenance,
                            "local action (repository-root relative)",
                        )
                    ]
            return [
                _edge(
                    src,
                    None,
                    ref,
                    "unresolved",
                    provenance,
                    "local action not found in the repository",
                )
            ]
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

    # ---- Go ------------------------------------------------------------------------------
    def go(self, src: str, ref: Ref, provenance: str) -> list[RepoEdgeRecord]:
        raw = ref.raw
        for folder, mod in sorted(self.go_modules.items(), key=lambda kv: -len(kv[1])):
            if raw == mod or raw.startswith(mod + "/"):
                rel = raw[len(mod) :].strip("/")
                pkg = posixpath.join(folder, rel) if rel else folder
                pkg = pkg.strip("/")
                hits = sorted(
                    p
                    for p in self.files
                    if p.endswith(".go")
                    and not p.endswith("_test.go")
                    and posixpath.dirname(p) == pkg
                )
                if hits:
                    note = f"package of {len(hits)} files" if len(hits) > 1 else None
                    return [_edge(src, h, ref, "resolved", provenance, note) for h in hits[:8]]
                return [
                    _edge(
                        src,
                        None,
                        ref,
                        "unresolved",
                        provenance,
                        "package folder not found in the repository",
                    )
                ]
        if "." not in raw.split("/")[0]:
            return [_edge(src, None, ref, "external", provenance, "standard library")]
        return [
            _edge(
                src, None, ref, "external", provenance, "module dependency (not in the repository)"
            )
        ]

    # ---- Java ----------------------------------------------------------------------------
    def java(self, src: str, ref: Ref, provenance: str) -> list[RepoEdgeRecord]:
        raw = ref.raw
        if raw.startswith(("java.", "javax.", "jdk.", "sun.")):
            return [_edge(src, None, ref, "external", provenance, "Java standard library")]
        if self._java is None:
            self._java = [p for p in self.files if p.endswith(".java")]
        parts = raw.removesuffix(".*").split(".")
        if raw.endswith(".*"):
            suffix = "/".join(parts) + "/"
            hits = sorted(
                p
                for p in self._java
                if ("/" + posixpath.dirname(p) + "/").endswith("/" + suffix)
                or (posixpath.dirname(p) + "/") == suffix
            )
            if hits:
                return [
                    _edge(src, h, ref, "resolved", provenance, f"package of {len(hits)} files")
                    for h in hits[:8]
                ]
        else:
            for cut in (0, 1):  # a static import names a member after the class
                cand = "/".join(parts[: len(parts) - cut]) + ".java"
                hits = sorted(p for p in self._java if p == cand or p.endswith("/" + cand))
                if hits:
                    return [
                        _edge(
                            src,
                            hits[0],
                            ref,
                            "resolved",
                            provenance,
                            None if len(hits) == 1 else "several files match; the first is shown",
                        )
                    ]
        return [
            _edge(
                src,
                None,
                ref,
                "external",
                provenance,
                "not found in the repository (library or generated)",
            )
        ]

    # ---- Rust ----------------------------------------------------------------------------
    def rust(self, src: str, ref: Ref, provenance: str) -> list[RepoEdgeRecord]:
        raw = ref.raw
        here = posixpath.dirname(src)
        base = posixpath.basename(src)
        if ref.note == "mod declaration":
            folder = (
                here
                if base in {"mod.rs", "lib.rs", "main.rs"}
                else posixpath.join(here, base.removesuffix(".rs"))
            )
            for cand in (
                posixpath.join(folder, raw + ".rs"),
                posixpath.join(folder, raw, "mod.rs"),
            ):
                if cand in self.files:
                    return [_edge(src, cand, ref, "resolved", provenance)]
            return [_edge(src, None, ref, "unresolved", provenance, "module file not found")]
        segs = [x for x in raw.replace("{", "").replace("}", "").replace(" ", "").split("::") if x]
        if not segs or segs[0] in {"std", "core", "alloc"}:
            return [_edge(src, None, ref, "external", provenance, "standard library")]
        if segs[0] in {"crate", "self", "super"}:
            root = here
            while root and not (
                posixpath.join(root, "lib.rs") in self.files
                or posixpath.join(root, "main.rs") in self.files
            ):
                root = posixpath.dirname(root)
            if segs[0] == "crate" and (
                posixpath.join(root, "lib.rs") in self.files
                or posixpath.join(root, "main.rs") in self.files
            ):
                path = segs[1:]
                for n in range(len(path), 0, -1):
                    for cand in (
                        posixpath.join(root, *path[:n]) + ".rs",
                        posixpath.join(root, *path[:n], "mod.rs"),
                    ):
                        if cand in self.files and cand != src:
                            return [_edge(src, cand, ref, "resolved", provenance)]
            return [
                _edge(
                    src,
                    None,
                    ref,
                    "unresolved",
                    provenance,
                    "module path not found in the repository",
                )
            ]
        return [
            _edge(
                src, None, ref, "external", provenance, "crate dependency (not in the repository)"
            )
        ]

    # ---- Ruby ----------------------------------------------------------------------------
    def ruby(self, src: str, ref: Ref, provenance: str) -> list[RepoEdgeRecord]:
        name = ref.raw if ref.raw.endswith(".rb") else ref.raw + ".rb"
        if ref.note == "require_relative":
            cand = posixpath.normpath(posixpath.join(posixpath.dirname(src), name))
            if cand in self.files:
                return [_edge(src, cand, ref, "resolved", provenance)]
            return [_edge(src, None, ref, "unresolved", provenance, "file not found")]
        for cand in (
            posixpath.join("lib", name),
            name,
            posixpath.join(posixpath.dirname(src), name),
        ):
            cand = posixpath.normpath(cand)
            if cand in self.files and cand != src:
                return [_edge(src, cand, ref, "resolved", provenance)]
        return [_edge(src, None, ref, "external", provenance, "gem or standard library")]

    # ---- shell ---------------------------------------------------------------------------
    def shell(self, src: str, ref: Ref, provenance: str) -> list[RepoEdgeRecord]:
        raw = ref.raw
        if not raw or "$" in raw or "`" in raw:
            return [_edge(src, None, ref, "unresolved", provenance, "path computed at runtime")]
        for cand in (
            posixpath.normpath(posixpath.join(posixpath.dirname(src), raw)),
            posixpath.normpath(raw.lstrip("/")),
        ):
            if cand in self.files and cand != src and not cand.startswith(".."):
                return [
                    _edge(
                        src,
                        cand,
                        ref,
                        "heuristic",
                        provenance,
                        "relative to the script's folder or the repository root; the real base is the working directory at run time",
                    )
                ]
        return [_edge(src, None, ref, "unresolved", provenance, "file not found in the repository")]

    def resolve(self, src: str, language: str, ref: Ref, provenance: str) -> list[RepoEdgeRecord]:
        if language == "go":
            return self.go(src, ref, provenance)
        if language == "java":
            return self.java(src, ref, provenance)
        if language == "rust":
            return self.rust(src, ref, provenance)
        if language == "ruby":
            return self.ruby(src, ref, provenance)
        if language == "shell":
            return self.shell(src, ref, provenance)
        if language == "python":
            return self.python(src, ref, provenance)
        if language in {"javascript", "typescript"}:
            return self.javascript(src, ref, provenance)
        return self.web(src, ref, provenance)
