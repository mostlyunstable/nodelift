# ruff: noqa: E501
from typing import Any

import tree_sitter_javascript as ts_js
import tree_sitter_typescript as ts_ts
from tree_sitter import Language, Node, Parser

from app.domain.records import RepoDiagnosticRecord, RepoSymbolRecord
from app.explorer.analysis.base import Binding, CallSite, FileAnalysis, Ref

SOURCE = "tree-sitter.javascript"
_LANGS: dict[str, Language] = {}


def _language(path: str) -> Language:
    low = path.lower()
    key = "tsx" if low.endswith(".tsx") else "ts" if low.endswith((".ts", ".mts", ".cts")) else "js"
    if key not in _LANGS:
        _LANGS[key] = Language(
            {"tsx": ts_ts.language_tsx, "ts": ts_ts.language_typescript, "js": ts_js.language}[
                key
            ]()
        )
    return _LANGS[key]


def _text(n: Node | None) -> str:
    return n.text.decode("utf-8", "replace") if n is not None and n.text is not None else ""


def _string_value(n: Node | None) -> str | None:
    """The contents of a plain string literal; None for template strings with substitutions."""
    if n is None:
        return None
    if n.type == "string":
        frags = [c for c in n.children if c.type == "string_fragment"]
        return "".join(_text(c) for c in frags) if frags else ""
    if n.type == "template_string" and not any(
        c.type == "template_substitution" for c in n.children
    ):
        return _text(n)[1:-1]
    return None


def _first_error(root: Node) -> Node | None:
    stack = [root]
    while stack:
        n = stack.pop()
        if n.type == "ERROR" or n.is_missing:
            return n
        stack.extend(reversed(n.children))
    return None


def _chain(fn: Node) -> tuple[list[str], Node] | None:
    """`a.b.c` -> (['a','b','c'], node of 'c'). None for anything not a plain dotted name."""
    names: list[str] = []
    last: Node | None = None
    cur: Node | None = fn
    while cur is not None and cur.type == "member_expression":
        prop = cur.child_by_field_name("property")
        if prop is None or prop.type != "property_identifier":
            return None
        if last is None:
            last = prop
        names.append(_text(prop))
        cur = cur.child_by_field_name("object")
    if cur is None or cur.type not in {"identifier", "this"}:
        return None
    names.append(_text(cur))
    if last is None:
        last = cur
    names.reverse()
    return names, last


def _bindings_for_import(n: Node, module: str, out: FileAnalysis) -> None:
    for c in n.children:
        if c.type != "import_clause":
            continue
        for part in c.children:
            if part.type == "identifier":  # default import
                out.bindings.append(Binding(_text(part), module, 0, "default"))
            elif part.type == "namespace_import":
                ident = next((x for x in part.children if x.type == "identifier"), None)
                if ident is not None:
                    out.bindings.append(Binding(_text(ident), module, 0, None))
            elif part.type == "named_imports":
                for spec in part.children:
                    if spec.type != "import_specifier":
                        continue
                    name = _text(spec.child_by_field_name("name"))
                    alias = _text(spec.child_by_field_name("alias")) or name
                    out.bindings.append(Binding(alias, module, 0, name))


def _bindings_for_require(decl: Node, module: str, out: FileAnalysis) -> None:
    target = decl.child_by_field_name("name")
    if target is None:
        return
    if target.type == "identifier":
        out.bindings.append(Binding(_text(target), module, 0, None))
    elif target.type == "object_pattern":
        for p in target.children:
            if p.type == "shorthand_property_identifier_pattern":
                out.bindings.append(Binding(_text(p), module, 0, _text(p)))
            elif p.type == "pair_pattern":
                key, val = p.child_by_field_name("key"), p.child_by_field_name("value")
                if key is not None and val is not None and val.type == "identifier":
                    out.bindings.append(Binding(_text(val), module, 0, _text(key)))


def _walk(
    n: Node,
    path: str,
    out: FileAnalysis,
    exported: bool = False,
    cls: str | None = None,
    scope: str | None = None,
) -> None:
    t = n.type
    line = n.start_point[0] + 1
    end = n.end_point[0] + 1
    if t == "import_statement":
        src = _string_value(n.child_by_field_name("source"))
        if src is not None:
            out.refs.append(Ref(src, "import", line))
            _bindings_for_import(n, src, out)
        return
    if t == "export_statement":
        src = _string_value(n.child_by_field_name("source"))
        if src is not None:
            out.refs.append(Ref(src, "reexport", line))
            return
        for c in n.children:
            _walk(c, path, out, exported=True, cls=cls, scope=scope)
        return
    if t == "call_expression":
        fn = n.child_by_field_name("function")
        args = n.child_by_field_name("arguments")
        first = next(
            (c for c in (args.named_children if args else []) if c.type != "comment"), None
        )
        chain_info = _chain(fn) if fn is not None else None
        if chain_info is not None:
            names, last = chain_info
            out.calls.append(
                CallSite(
                    chain=tuple(names),
                    line=last.start_point[0] + 1,
                    column=last.start_point[1] + 1,
                    end_column=last.end_point[1] + 1,
                    scope=scope,
                    cls=cls,
                )
            )
        if fn is not None and (_text(fn) == "require" or fn.type == "import"):
            val = _string_value(first)
            kind = "import" if _text(fn) == "require" else "dynamic_import"
            if val is not None:
                out.refs.append(Ref(val, kind, line))
            elif first is not None:
                out.refs.append(
                    Ref("", kind, line, note="target computed at runtime", dynamic=True)
                )
    kind_by_type = {
        "function_declaration": "function", "generator_function_declaration": "function",
        "class_declaration": "class", "interface_declaration": "interface",
        "type_alias_declaration": "type", "enum_declaration": "enum",
        "abstract_class_declaration": "class",
    }  # fmt: skip
    if t in kind_by_type:
        name = _text(n.child_by_field_name("name"))
        if name:
            out.symbols.append(
                RepoSymbolRecord(
                    path=path,
                    name=name,
                    kind=kind_by_type[t],
                    line=line,
                    end_line=end,
                    exported=exported,
                )
            )
        if t in {"class_declaration", "abstract_class_declaration"}:
            body = n.child_by_field_name("body")
            for c in body.named_children if body else []:
                _walk(c, path, out, False, name, None)
            return
    elif t == "method_definition" and cls:
        name = _text(n.child_by_field_name("name"))
        out.symbols.append(
            RepoSymbolRecord(
                path=path,
                name=name,
                kind="method",
                line=line,
                end_line=end,
                parent=cls,
                exported=True,
            )
        )
    elif t == "variable_declarator":
        fn_value = n.child_by_field_name("value")
        if fn_value is not None and fn_value.type == "call_expression":
            callee = fn_value.child_by_field_name("function")
            args = fn_value.child_by_field_name("arguments")
            arg = next(
                (c for c in (args.named_children if args else []) if c.type != "comment"), None
            )
            mod = _string_value(arg)
            if callee is not None and _text(callee) == "require" and mod is not None:
                _bindings_for_require(n, mod, out)
        if fn_value is not None and fn_value.type in {
            "arrow_function",
            "function_expression",
            "function",
        }:
            out.symbols.append(
                RepoSymbolRecord(
                    path=path, name=_text(n.child_by_field_name("name")), kind="function",
                    line=line, end_line=end, exported=exported,
                )
            )  # fmt: skip
    child_scope = scope
    if t in {"function_declaration", "generator_function_declaration"}:
        child_scope = _text(n.child_by_field_name("name")) or scope
    elif t == "method_definition" and cls:
        child_scope = f"{cls}.{_text(n.child_by_field_name('name'))}"
    elif t == "variable_declarator":
        fv = n.child_by_field_name("value")
        if fv is not None and fv.type in {"arrow_function", "function_expression", "function"}:
            child_scope = _text(n.child_by_field_name("name")) or scope
    for c in n.children:
        _walk(
            c,
            path,
            out,
            exported if t == "lexical_declaration" else False,
            cls if t != "class_declaration" else None,
            child_scope,
        )


def _is_flow(text: str) -> bool:
    """Files that declare `@flow` use Flow type syntax, which this parser does not read."""
    return "@flow" in text[:2048]


class JavaScriptAnalyzer:
    id = SOURCE
    languages = frozenset({"javascript", "typescript"})

    def analyze(self, path: str, text: str) -> FileAnalysis:
        out = FileAnalysis()
        parser = Parser(_language(path))
        tree = parser.parse(text.encode("utf-8"))
        root: Any = tree.root_node
        if root.has_error and not _is_flow(text):
            bad = _first_error(root)
            ln = (bad.start_point[0] + 1) if bad is not None else 1
            col = (bad.start_point[1] + 1) if bad is not None else 0
            out.diagnostics.append(
                RepoDiagnosticRecord(
                    path=path, line=ln, column=col, severity="info", code="parser_note",
                    message=(
                        "The parser could not fully read this file. It may use syntax the parser "
                        "does not know (for example Flow types), so this is a note, not a verdict."
                    ),
                    source=SOURCE,
                )
            )  # fmt: skip
        _walk(root, path, out)
        return out
