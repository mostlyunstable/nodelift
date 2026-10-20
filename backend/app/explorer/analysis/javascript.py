# ruff: noqa: E501
from typing import Any

import tree_sitter_javascript as ts_js
import tree_sitter_typescript as ts_ts
from tree_sitter import Language, Node, Parser

from app.domain.records import RepoDiagnosticRecord, RepoSymbolRecord
from app.explorer.analysis.base import FileAnalysis, Ref

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


def _walk(
    n: Node, path: str, out: FileAnalysis, exported: bool = False, cls: str | None = None
) -> None:
    t = n.type
    line = n.start_point[0] + 1
    end = n.end_point[0] + 1
    if t == "import_statement":
        src = _string_value(n.child_by_field_name("source"))
        if src is not None:
            out.refs.append(Ref(src, "import", line))
        return
    if t == "export_statement":
        src = _string_value(n.child_by_field_name("source"))
        if src is not None:
            out.refs.append(Ref(src, "reexport", line))
            return
        for c in n.children:
            _walk(c, path, out, exported=True, cls=cls)
        return
    if t == "call_expression":
        fn = n.child_by_field_name("function")
        args = n.child_by_field_name("arguments")
        first = next(
            (c for c in (args.named_children if args else []) if c.type != "comment"), None
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
                _walk(c, path, out, False, name)
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
    for c in n.children:
        _walk(
            c,
            path,
            out,
            exported if t == "lexical_declaration" else False,
            cls if t != "class_declaration" else None,
        )


class JavaScriptAnalyzer:
    id = SOURCE
    languages = frozenset({"javascript", "typescript"})

    def analyze(self, path: str, text: str) -> FileAnalysis:
        out = FileAnalysis()
        parser = Parser(_language(path))
        tree = parser.parse(text.encode("utf-8"))
        root: Any = tree.root_node
        if root.has_error:
            bad = _first_error(root)
            ln = (bad.start_point[0] + 1) if bad is not None else 1
            col = (bad.start_point[1] + 1) if bad is not None else 0
            out.diagnostics.append(
                RepoDiagnosticRecord(
                    path=path, line=ln, column=col, severity="warning", code="syntax_error",
                    message=(
                        "The parser reported a syntax error here "
                        "(it may be newer syntax the parser does not know)"
                    ),
                    source=SOURCE,
                )
            )  # fmt: skip
        _walk(root, path, out)
        return out
