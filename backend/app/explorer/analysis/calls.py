# ruff: noqa: E501
"""Tie call sites to the definitions they call, where that can be shown from the source alone.

Resolved: a name bound by an import (or defined in the same file) and called directly, or a
`module.function()` / `Class.method()` through such a binding. Heuristic: `self.method()` /
`this.method()` resolved to the enclosing class (an override in a subclass is not considered).
Everything else (calls on values, dynamic dispatch, decorators, callbacks, `getattr`) is left out
rather than guessed.
"""

from app.domain.records import RepoReferenceRecord, RepoSymbolRecord
from app.explorer.analysis.base import Binding, CallSite, FileAnalysis, Ref
from app.explorer.analysis.resolve import Resolver

SymIndex = dict[tuple[str | None, str], RepoSymbolRecord]
CALLABLE = {"function", "class", "method"}


def _qual(s: RepoSymbolRecord) -> str:
    return f"{s.parent}.{s.name}" if s.parent else s.name


def _ref(
    src: str,
    call: CallSite,
    sym: RepoSymbolRecord,
    confidence: str,
    provenance: str,
    note: str | None = None,
) -> RepoReferenceRecord:
    return RepoReferenceRecord(
        path=src, line=call.line, column=call.column, end_column=call.end_column, name=call.chain[-1],
        kind="call", scope=call.scope, dst_path=sym.path, dst_symbol=_qual(sym), dst_line=sym.line,
        confidence=confidence, provenance=provenance, note=note,
    )  # fmt: skip


def _find(idx: SymIndex | None, parent: str | None, name: str) -> RepoSymbolRecord | None:
    if idx is None:
        return None
    s = idx.get((parent, name))
    return s if s is not None and s.kind in CALLABLE else None


def _in_module(
    syms: dict[str, SymIndex], file: str | None, tail: list[str]
) -> RepoSymbolRecord | None:
    """`tail` is what follows the module: [fn] or [Class, method]."""
    if file is None or not tail:
        return None
    if len(tail) == 1:
        return _find(syms.get(file), None, tail[0])
    if len(tail) == 2:
        return _find(syms.get(file), tail[0], tail[1])
    return None


def _python(
    src: str,
    call: CallSite,
    binds: dict[str, Binding],
    syms: dict[str, SymIndex],
    rs: Resolver,
    prov: str,
) -> RepoReferenceRecord | None:
    chain = list(call.chain)
    head = chain[0]
    b = binds.get(head)
    if b is not None:
        if b.name is None:
            if b.py_plain_import:  # `import a.b` then `a.b.fn()`
                for cut in (1, 2):
                    if len(chain) > cut:
                        mod = ".".join(chain[:-cut])
                        hit = _in_module(syms, rs.python_module(src, mod, 0), chain[-cut:])
                        if hit:
                            return _ref(src, call, hit, "resolved", prov)
                return None
            for cut in (1, 2):  # `import a.b as m` / from-bound module
                if len(chain) > cut:
                    mod = ".".join([b.module, *chain[1:-cut]])
                    hit = _in_module(syms, rs.python_module(src, mod, b.level), chain[-cut:])
                    if hit:
                        return _ref(src, call, hit, "resolved", prov)
            return None
        sub = rs.python_module(src, f"{b.module}.{b.name}" if b.module else b.name, b.level)
        mod_file = rs.python_module(src, b.module, b.level)
        if sub and sub != mod_file:  # `from pkg import module` then `module.fn()`
            hit = _in_module(syms, sub, chain[1:])
            return _ref(src, call, hit, "resolved", prov) if hit else None
        hit = _in_module(syms, mod_file, [b.name, *chain[1:]])
        return _ref(src, call, hit, "resolved", prov) if hit else None
    here = syms.get(src)
    if len(chain) == 1:
        hit = _find(here, None, head)
        return _ref(src, call, hit, "resolved", prov) if hit else None
    if len(chain) == 2:
        if head in {"self", "cls"} and call.cls:
            hit = _find(here, call.cls, chain[1])
            if hit:
                return _ref(
                    src,
                    call,
                    hit,
                    "heuristic",
                    prov,
                    "self.method resolved to this class; overrides in subclasses are not considered",
                )
        hit = _find(here, head, chain[1]) if _find(here, None, head) else None
        if hit:
            return _ref(src, call, hit, "resolved", prov)
    return None


def _javascript(
    src: str,
    call: CallSite,
    binds: dict[str, Binding],
    syms: dict[str, SymIndex],
    rs: Resolver,
    prov: str,
) -> RepoReferenceRecord | None:
    chain = list(call.chain)
    head = chain[0]
    b = binds.get(head)
    if b is not None:
        if b.name == "default":
            return None  # which symbol a default export names is not visible here
        target = rs.js_module(src, b.module)
        if b.name is None:
            hit = _in_module(syms, target, chain[1:])  # namespace / require('x').fn()
        else:
            hit = _in_module(syms, target, [b.name, *chain[1:]])
        return _ref(src, call, hit, "resolved", prov) if hit else None
    here = syms.get(src)
    if len(chain) == 1:
        hit = _find(here, None, head)
        return _ref(src, call, hit, "resolved", prov) if hit else None
    if len(chain) == 2:
        if head == "this" and call.cls:
            hit = _find(here, call.cls, chain[1])
            if hit:
                return _ref(
                    src,
                    call,
                    hit,
                    "heuristic",
                    prov,
                    "this.method resolved to this class; overrides in subclasses are not considered",
                )
        hit = _find(here, head, chain[1]) if _find(here, None, head) else None
        if hit:
            return _ref(src, call, hit, "resolved", prov)
    return None


def resolve_calls(
    analyses: dict[str, FileAnalysis],
    languages: dict[str, str],
    providers: dict[str, str],
    resolver: Resolver,
    cap: int = 200_000,
) -> list[RepoReferenceRecord]:
    syms: dict[str, SymIndex] = {}
    for path, a in analyses.items():
        idx: SymIndex = {}
        for s in a.symbols:
            idx.setdefault((s.parent, s.name), s)
        syms[path] = idx
    out: list[RepoReferenceRecord] = []
    for path, a in analyses.items():
        lang = languages[path]
        binds = {b.local: b for b in a.bindings}
        fn = (
            _python
            if lang == "python"
            else _javascript
            if lang in {"javascript", "typescript"}
            else None
        )
        if fn is None:
            continue
        for call in a.calls:
            if len(out) >= cap:
                return out
            r = fn(path, call, binds, syms, resolver, providers[path])
            if r is not None:
                out.append(r)
    return out


__all__ = ["Ref", "resolve_calls"]
