# ruff: noqa: E501
"""Go, Java, Rust, Ruby, shell, Markdown, YAML, JSON and SQL: imports/references and symbols.

Each analyzer only reports what is written in the file. Resolution to repository files happens in
`resolve.py`; SQL table references are matched to CREATE statements by name afterwards (heuristic).
"""

import json
from typing import Any

import tree_sitter_bash as ts_bash
import tree_sitter_go as ts_go
import tree_sitter_java as ts_java
import tree_sitter_ruby as ts_ruby
import tree_sitter_rust as ts_rust
import yaml
from markdown_it import MarkdownIt
from tree_sitter import Language, Node, Parser

from app.domain.records import RepoDiagnosticRecord, RepoSymbolRecord
from app.explorer.analysis.base import FileAnalysis, Ref


def _t(n: Node | None) -> str:
    return n.text.decode("utf-8", "replace") if n is not None and n.text is not None else ""


def _str(n: Node) -> str:
    return _t(n).strip("\"'`")


def _sym(
    path: str, name: str, kind: str, n: Node, parent: str | None = None, exported: bool = True
) -> RepoSymbolRecord:
    return RepoSymbolRecord(
        path=path,
        name=name,
        kind=kind,
        line=n.start_point[0] + 1,
        end_line=n.end_point[0] + 1,
        parent=parent,
        exported=exported,
    )


def _error(path: str, root: Node, source: str) -> list[RepoDiagnosticRecord]:
    if not root.has_error:
        return []
    stack, bad = [root], None
    while stack:
        n = stack.pop()
        if n.type == "ERROR" or n.is_missing:
            bad = n
            break
        stack.extend(reversed(n.children))
    ln = bad.start_point[0] + 1 if bad is not None else 1
    return [
        RepoDiagnosticRecord(
            path=path,
            line=ln,
            column=(bad.start_point[1] + 1) if bad is not None else 0,
            severity="warning",
            code="syntax_error",
            message="The parser reported a syntax error here (it may be newer syntax the parser does not know)",
            source=source,
        )
    ]


def _walk(root: Node) -> Any:
    stack = [root]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(n.children))


# ---------------------------------------------------------------------------------- Go
class GoAnalyzer:
    id = "tree-sitter.go"
    languages = frozenset({"go"})
    _lang = Language(ts_go.language())

    def analyze(self, path: str, text: str) -> FileAnalysis:
        out = FileAnalysis()
        root = Parser(self._lang).parse(text.encode()).root_node
        out.diagnostics += _error(path, root, self.id)
        for n in _walk(root):
            if n.type == "import_spec":
                lit = next(
                    (
                        c
                        for c in n.children
                        if c.type == "interpreted_string_literal" or c.type == "raw_string_literal"
                    ),
                    None,
                )
                if lit is not None:
                    out.refs.append(Ref(_str(lit), "import", n.start_point[0] + 1))
            elif n.type == "function_declaration":
                nm = _t(n.child_by_field_name("name"))
                out.symbols.append(_sym(path, nm, "function", n, exported=nm[:1].isupper()))
            elif n.type == "method_declaration":
                nm = _t(n.child_by_field_name("name"))
                recv = n.child_by_field_name("receiver")
                tn = (
                    next((c for c in _walk(recv) if c.type == "type_identifier"), None)
                    if recv is not None
                    else None
                )
                out.symbols.append(
                    _sym(path, nm, "method", n, parent=_t(tn) or None, exported=nm[:1].isupper())
                )
            elif n.type == "type_spec":
                nm = _t(n.child_by_field_name("name"))
                typ = n.child_by_field_name("type")
                out.symbols.append(
                    _sym(
                        path,
                        nm,
                        "interface"
                        if typ is not None and typ.type == "interface_type"
                        else "class",
                        n,
                        exported=nm[:1].isupper(),
                    )
                )
        return out


# -------------------------------------------------------------------------------- Java
class JavaAnalyzer:
    id = "tree-sitter.java"
    languages = frozenset({"java"})
    _lang = Language(ts_java.language())

    def analyze(self, path: str, text: str) -> FileAnalysis:
        out = FileAnalysis()
        root = Parser(self._lang).parse(text.encode()).root_node
        out.diagnostics += _error(path, root, self.id)

        def visit(n: Node, cls: str | None) -> None:
            for c in n.children:
                if c.type == "import_declaration":
                    ident = next(
                        (x for x in c.children if x.type in {"scoped_identifier", "identifier"}),
                        None,
                    )
                    if ident is not None:
                        wildcard = any(x.type == "asterisk" for x in c.children)
                        raw = _t(ident) + (".*" if wildcard else "")
                        out.refs.append(
                            Ref(
                                raw,
                                "import",
                                c.start_point[0] + 1,
                                note="static import"
                                if any(x.type == "static" for x in c.children)
                                else None,
                            )
                        )
                elif c.type in {
                    "class_declaration",
                    "interface_declaration",
                    "enum_declaration",
                    "record_declaration",
                }:
                    nm = _t(c.child_by_field_name("name"))
                    out.symbols.append(
                        _sym(
                            path,
                            nm,
                            "interface"
                            if c.type == "interface_declaration"
                            else "enum"
                            if c.type == "enum_declaration"
                            else "class",
                            c,
                            exported="public"
                            in _t(next((x for x in c.children if x.type == "modifiers"), None)),
                        )
                    )
                    body = c.child_by_field_name("body")
                    if body is not None:
                        visit(body, nm)
                elif c.type in {"method_declaration", "constructor_declaration"} and cls:
                    nm = _t(c.child_by_field_name("name"))
                    out.symbols.append(
                        _sym(
                            path,
                            nm,
                            "method",
                            c,
                            parent=cls,
                            exported="private"
                            not in _t(next((x for x in c.children if x.type == "modifiers"), None)),
                        )
                    )
                else:
                    visit(c, cls)

        visit(root, None)
        return out


# -------------------------------------------------------------------------------- Rust
class RustAnalyzer:
    id = "tree-sitter.rust"
    languages = frozenset({"rust"})
    _lang = Language(ts_rust.language())

    def analyze(self, path: str, text: str) -> FileAnalysis:
        out = FileAnalysis()
        root = Parser(self._lang).parse(text.encode()).root_node
        out.diagnostics += _error(path, root, self.id)

        def vis(n: Node) -> bool:
            return any(c.type == "visibility_modifier" for c in n.children)

        def visit(n: Node, impl: str | None) -> None:
            for c in n.children:
                if c.type == "mod_item" and not any(
                    x.type == "declaration_list" for x in c.children
                ):
                    out.refs.append(
                        Ref(
                            _t(c.child_by_field_name("name")),
                            "import",
                            c.start_point[0] + 1,
                            note="mod declaration",
                        )
                    )
                elif c.type == "use_declaration":
                    arg = c.child_by_field_name("argument")
                    if arg is not None:
                        out.refs.append(Ref(_t(arg), "import", c.start_point[0] + 1))
                elif c.type == "function_item":
                    out.symbols.append(
                        _sym(
                            path,
                            _t(c.child_by_field_name("name")),
                            "method" if impl else "function",
                            c,
                            parent=impl,
                            exported=vis(c),
                        )
                    )
                elif c.type in {"struct_item", "enum_item", "trait_item"}:
                    out.symbols.append(
                        _sym(
                            path,
                            _t(c.child_by_field_name("name")),
                            "interface"
                            if c.type == "trait_item"
                            else "enum"
                            if c.type == "enum_item"
                            else "class",
                            c,
                            exported=vis(c),
                        )
                    )
                elif c.type == "impl_item":
                    tn = c.child_by_field_name("type")
                    body = c.child_by_field_name("body")
                    if body is not None:
                        visit(body, _t(tn) or None)
                elif c.type in {"mod_item", "declaration_list"}:
                    visit(c, impl)

        visit(root, None)
        return out


# -------------------------------------------------------------------------------- Ruby
class RubyAnalyzer:
    id = "tree-sitter.ruby"
    languages = frozenset({"ruby"})
    _lang = Language(ts_ruby.language())

    def analyze(self, path: str, text: str) -> FileAnalysis:
        out = FileAnalysis()
        root = Parser(self._lang).parse(text.encode()).root_node
        out.diagnostics += _error(path, root, self.id)

        def visit(n: Node, cls: str | None) -> None:
            for c in n.children:
                if c.type == "call":
                    meth = _t(c.child_by_field_name("method")) or (
                        _t(c.children[0]) if c.children else ""
                    )
                    args = next((x for x in c.children if x.type == "argument_list"), None)
                    first = (
                        args.named_children[0] if args is not None and args.named_children else None
                    )
                    if (
                        meth in {"require", "require_relative", "load"}
                        and first is not None
                        and first.type == "string"
                    ):
                        out.refs.append(
                            Ref(
                                _str(first),
                                "import",
                                c.start_point[0] + 1,
                                note="require_relative" if meth == "require_relative" else None,
                            )
                        )
                    visit(c, cls)
                elif c.type in {"class", "module"}:
                    nm = _t(c.child_by_field_name("name"))
                    out.symbols.append(_sym(path, nm, "class", c))
                    visit(c, nm)
                elif c.type in {"method", "singleton_method"}:
                    out.symbols.append(
                        _sym(
                            path,
                            _t(c.child_by_field_name("name")),
                            "method" if cls else "function",
                            c,
                            parent=cls,
                        )
                    )
                else:
                    visit(c, cls)

        visit(root, None)
        return out


# -------------------------------------------------------------------------------- shell
class ShellAnalyzer:
    id = "tree-sitter.bash"
    languages = frozenset({"shell"})
    _lang = Language(ts_bash.language())

    def analyze(self, path: str, text: str) -> FileAnalysis:
        out = FileAnalysis()
        root = Parser(self._lang).parse(text.encode()).root_node
        out.diagnostics += _error(path, root, self.id)
        for n in _walk(root):
            if n.type == "function_definition":
                nm = _t(next((c for c in n.children if c.type == "word"), None))
                out.symbols.append(_sym(path, nm, "function", n))
            elif n.type == "command":
                words = [c for c in n.children if c.type in {"word", "string", "raw_string"}]
                name = _t(n.child_by_field_name("name"))
                arg = next(
                    (
                        w
                        for w in words
                        if w is not n.child_by_field_name("name") and not _t(w).startswith("-")
                    ),
                    None,
                )
                if name in {"source", "."} and arg is not None:
                    out.refs.append(Ref(_str(arg), "import", n.start_point[0] + 1, note="sourced"))
                elif (
                    name in {"bash", "sh", "zsh"} and arg is not None and _str(arg).endswith(".sh")
                ):
                    out.refs.append(
                        Ref(_str(arg), "reference", n.start_point[0] + 1, note="run as a script")
                    )
        return out


# -------------------------------------------------------------------------------- Markdown
class MarkdownAnalyzer:
    id = "markdown-it"
    languages = frozenset({"markdown"})

    def analyze(self, path: str, text: str) -> FileAnalysis:
        out = FileAnalysis()
        md = MarkdownIt("commonmark")
        for tok in md.parse(text):
            if tok.type == "heading_open" and tok.map:
                level = int(tok.tag[1:])
                title = ""
                # the inline token that follows holds the heading text
                out.symbols.append(
                    RepoSymbolRecord(
                        path=path,
                        name=title,
                        kind="heading",
                        line=tok.map[0] + 1,
                        end_line=tok.map[1],
                        parent=None,
                        exported=level <= 2,
                    )
                )
            if tok.type == "inline":
                if out.symbols and out.symbols[-1].name == "" and out.symbols[-1].kind == "heading":
                    s = out.symbols[-1]
                    out.symbols[-1] = RepoSymbolRecord(
                        path=s.path,
                        name=tok.content.strip()[:120],
                        kind="heading",
                        line=s.line,
                        end_line=s.end_line,
                        parent=None,
                        exported=s.exported,
                    )
                for child in tok.children or []:
                    href = (
                        child.attrGet("href")
                        if child.type == "link_open"
                        else child.attrGet("src")
                        if child.type == "image"
                        else None
                    )
                    if isinstance(href, str):
                        out.refs.append(
                            Ref(
                                href,
                                "reference",
                                (tok.map[0] + 1) if tok.map else 1,
                                note="link" if child.type == "link_open" else "image",
                            )
                        )
        return out


# -------------------------------------------------------------------------------- YAML
_YAML_PATH_KEYS = {
    "uses",
    "env_file",
    "file",
    "path",
    "include",
    "extends",
    "script",
    "dockerfile",
    "context",
    "$ref",
    "requirements",
    "config",
    "entrypoint",
}


class YamlAnalyzer:
    id = "pyyaml"
    languages = frozenset({"yaml"})

    def analyze(self, path: str, text: str) -> FileAnalysis:
        out = FileAnalysis()
        try:
            docs = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
        except yaml.YAMLError as e:
            mark = getattr(e, "problem_mark", None)
            out.diagnostics.append(
                RepoDiagnosticRecord(
                    path=path,
                    line=(mark.line + 1) if mark else 1,
                    column=(mark.column + 1) if mark else 0,
                    severity="error",
                    code="syntax_error",
                    message=f"YAML error: {getattr(e, 'problem', 'invalid YAML')}",
                    source=self.id,
                )
            )
            return out

        def visit(node: yaml.Node) -> None:
            if isinstance(node, yaml.MappingNode):
                for k, v in node.value:
                    if (
                        isinstance(k, yaml.ScalarNode)
                        and isinstance(v, yaml.ScalarNode)
                        and k.value in _YAML_PATH_KEYS
                        and v.value.startswith(("./", "../"))
                    ):
                        out.refs.append(
                            Ref(v.value, "reference", v.start_mark.line + 1, note=f"{k.value}:")
                        )
                    visit(v)
            elif isinstance(node, yaml.SequenceNode):
                for item in node.value:
                    visit(item)

        for d in docs:
            if d is not None:
                visit(d)
        return out


# -------------------------------------------------------------------------------- JSON
_JSON_PATH_KEYS = {
    "main",
    "module",
    "types",
    "typings",
    "bin",
    "browser",
    "$ref",
    "extends",
    "file",
    "path",
}


_JSONC_NAMES = (
    "tsconfig",
    "jsconfig",
    ".eslintrc",
    ".babelrc",
    ".prettierrc",
    "devcontainer.json",
    "settings.json",
    "launch.json",
    "tasks.json",
)


def _is_jsonc(path: str) -> bool:
    low = path.lower()
    base = low.rsplit("/", 1)[-1]
    return (
        low.endswith(".jsonc")
        or base.startswith(_JSONC_NAMES)
        or "/.vscode/" in f"/{low}"
        or "/.devcontainer/" in f"/{low}"
    )


def _strip_jsonc(text: str) -> str:
    """Remove // and /* */ comments and trailing commas, leaving string contents alone."""
    out: list[str] = []
    i, n, in_str, esc = 0, len(text), False, False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
            out.append(c)
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        else:
            out.append(c)
        i += 1
    cleaned = "".join(out)
    # trailing commas before } or ]
    res, in_str, esc, k = [], False, False, 0
    while k < len(cleaned):
        c = cleaned[k]
        if in_str:
            res.append(c)
            esc = (not esc) if c == "\\" else False
            if c == '"' and not esc:
                in_str = False
        elif c == '"':
            in_str = True
            res.append(c)
        elif c == ",":
            j = k + 1
            while j < len(cleaned) and cleaned[j] in " \t\r\n":
                j += 1
            if j < len(cleaned) and cleaned[j] in "}]":
                k += 1
                continue
            res.append(c)
        else:
            res.append(c)
        k += 1
    return "".join(res)


class JsonAnalyzer:
    id = "json"
    languages = frozenset({"json"})

    def analyze(self, path: str, text: str) -> FileAnalysis:
        out = FileAnalysis()
        try:
            data = json.loads(_strip_jsonc(text) if _is_jsonc(path) else text)
        except json.JSONDecodeError as e:
            out.diagnostics.append(
                RepoDiagnosticRecord(
                    path=path,
                    line=e.lineno,
                    column=e.colno,
                    severity="warning" if _is_jsonc(path) else "error",
                    code="syntax_error",
                    message=f"Invalid JSON: {e.msg}",
                    source=self.id,
                )
            )
            return out
        lines = text.splitlines()

        def line_of(value: str) -> int:
            needle = json.dumps(value)
            for i, ln in enumerate(lines, 1):
                if needle in ln:
                    return i
            return 1

        def visit(node: object, key: str | None) -> None:
            if isinstance(node, dict):
                for k, v in node.items():
                    visit(v, k)
            elif isinstance(node, list):
                for v in node:
                    visit(v, key)
            elif isinstance(node, str) and key in _JSON_PATH_KEYS:
                target = node.split("#", 1)[0]
                if target.startswith(("./", "../")) or (
                    key in {"main", "module", "types", "typings", "bin"}
                    and "/" in target
                    and "://" not in target
                ):
                    out.refs.append(
                        Ref(
                            target if target.startswith(".") else f"./{target}",
                            "reference",
                            line_of(node),
                            note=f"{key}",
                        )
                    )

        visit(data, None)
        return out


# -------------------------------------------------------------------------------- SQL
class SqlAnalyzer:
    id = "sqlglot"
    languages = frozenset({"sql"})

    def analyze(self, path: str, text: str) -> FileAnalysis:
        import sqlglot
        from sqlglot import exp
        from sqlglot.errors import SqlglotError

        out = FileAnalysis()
        try:
            statements = sqlglot.parse(text, error_level=sqlglot.ErrorLevel.IGNORE)
        except SqlglotError as e:
            out.diagnostics.append(
                RepoDiagnosticRecord(
                    path=path,
                    line=1,
                    column=0,
                    severity="warning",
                    code="parse_failed",
                    message=f"Could not parse this SQL: {str(e)[:120]}",
                    source=self.id,
                )
            )
            return out
        lower = text.lower()

        def line_of(name: str) -> int:
            i = lower.find(name.lower())
            return lower.count("\n", 0, i) + 1 if i >= 0 else 1

        created: set[str] = set()
        for st in statements:
            if st is None:
                continue
            if isinstance(st, exp.Create):
                target = st.this
                tbl = (
                    target.find(exp.Table)
                    if target is not None and not isinstance(target, exp.Table)
                    else target
                )
                name = tbl.name if isinstance(tbl, exp.Table) else getattr(target, "name", "") or ""
                kind = str(st.args.get("kind") or "").lower()
                if name:
                    created.add(name.lower())
                    out.symbols.append(
                        RepoSymbolRecord(
                            path=path,
                            name=name,
                            kind="class" if kind in {"table", "view"} else "function",
                            line=line_of(name),
                            end_line=line_of(name),
                            parent=None,
                            exported=True,
                        )
                    )
            for t in st.find_all(exp.Table):
                nm = t.name
                if nm and nm.lower() not in created:
                    out.refs.append(Ref(nm, "table", line_of(nm)))
        return out
