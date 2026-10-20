# ruff: noqa: E501
import ast

from app.domain.records import RepoDiagnosticRecord, RepoSymbolRecord
from app.explorer.analysis.base import FileAnalysis, Ref

SOURCE = "python.ast"


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.out = FileAnalysis()
        self.type_checking = 0
        self.optional = 0
        self.scope: list[str] = []  # enclosing class names

    def _note(self) -> str | None:
        if self.type_checking:
            return "type-checking only (not imported at runtime)"
        if self.optional:
            return "optional (inside try/except)"
        return None

    def visit_Import(self, node: ast.Import) -> None:
        for a in node.names:
            self.out.refs.append(Ref(a.name, "import", node.lineno, note=self._note()))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        names = tuple(a.name for a in node.names)
        self.out.refs.append(
            Ref(node.module or "", "import", node.lineno, names, node.level, self._note())
        )

    def visit_If(self, node: ast.If) -> None:
        t = node.test
        is_tc = (isinstance(t, ast.Name) and t.id == "TYPE_CHECKING") or (
            isinstance(t, ast.Attribute) and t.attr == "TYPE_CHECKING"
        )
        if is_tc:
            self.type_checking += 1
            for n in node.body:
                self.visit(n)
            self.type_checking -= 1
            for n in node.orelse:
                self.visit(n)
        else:
            self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        catches_import = any(
            h.type is None
            or (
                isinstance(h.type, ast.Name) and h.type.id in {"ImportError", "ModuleNotFoundError"}
            )
            or (
                isinstance(h.type, ast.Tuple)
                and any(
                    isinstance(e, ast.Name) and e.id in {"ImportError", "ModuleNotFoundError"}
                    for e in h.type.elts
                )
            )
            for h in node.handlers
        )
        if catches_import:
            self.optional += 1
        for n in node.body:
            self.visit(n)
        if catches_import:
            self.optional -= 1
        for h in node.handlers:
            self.visit(h)
        for n in [*node.orelse, *node.finalbody]:
            self.visit(n)

    def visit_Call(self, node: ast.Call) -> None:
        f = node.func
        name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
        is_importlib = name in {"import_module", "__import__"} and (
            isinstance(f, ast.Name)
            or (
                isinstance(f, ast.Attribute)
                and isinstance(f.value, ast.Name)
                and f.value.id == "importlib"
            )
        )
        if is_importlib and node.args:
            a = node.args[0]
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                self.out.refs.append(Ref(a.value, "dynamic_import", node.lineno, note=self._note()))
            else:
                self.out.refs.append(
                    Ref(
                        "",
                        "dynamic_import",
                        node.lineno,
                        note="target computed at runtime",
                        dynamic=True,
                    )
                )
        self.generic_visit(node)

    def _sym(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, kind: str) -> None:
        parent = self.scope[-1] if self.scope else None
        self.out.symbols.append(
            RepoSymbolRecord(
                path=self.path, name=node.name, kind=kind, line=node.lineno,
                end_line=node.end_lineno or node.lineno, parent=parent,
                exported=not node.name.startswith("_")
                or (node.name.startswith("__") and node.name.endswith("__")),  # dunders are public API
            )
        )  # fmt: skip

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._sym(node, "method" if self.scope else "function")
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]  # noqa: N815

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._sym(node, "class")
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()


class PythonAnalyzer:
    id = SOURCE
    languages = frozenset({"python"})

    def analyze(self, path: str, text: str) -> FileAnalysis:
        try:
            tree = ast.parse(text, filename=path)
        except SyntaxError as e:
            out = FileAnalysis()
            out.diagnostics.append(
                RepoDiagnosticRecord(
                    path=path, line=e.lineno or 1, column=e.offset or 0, severity="error",
                    code="syntax_error", message=f"SyntaxError: {e.msg}", source=SOURCE,
                )
            )  # fmt: skip
            return out
        except (RecursionError, MemoryError, ValueError) as e:
            out = FileAnalysis()
            out.diagnostics.append(
                RepoDiagnosticRecord(
                    path=path, line=1, column=0, severity="warning", code="parse_failed",
                    message=f"Could not parse this file ({type(e).__name__})", source=SOURCE,
                )
            )  # fmt: skip
            return out
        v = _Visitor(path)
        v.visit(tree)
        return v.out
