from dataclasses import dataclass, field
from typing import Protocol

from app.domain.records import RepoDiagnosticRecord, RepoSymbolRecord


@dataclass(frozen=True)
class Ref:
    """One reference to another module/file, exactly as written in the source."""

    raw: str
    kind: str  # import | dynamic_import | reexport | reference | style_import
    line: int
    names: tuple[str, ...] = ()  # python: `from raw import names`
    level: int = 0  # python relative imports: number of leading dots
    note: str | None = None
    dynamic: bool = False  # the target is computed at runtime; it cannot be resolved statically


@dataclass(frozen=True)
class CallSite:
    """A call as written: `a.b.c()` is chain ('a','b','c'); the position is the last name."""

    chain: tuple[str, ...]
    line: int
    column: int  # 1-based
    end_column: int
    scope: str | None  # qualified enclosing function/method, None at module level
    cls: str | None  # enclosing class name, if any


@dataclass(frozen=True)
class Binding:
    """What a local name refers to because of an import."""

    local: str
    module: str  # raw specifier, as in Ref.raw
    level: int  # python relative-import dots
    name: str | None  # imported symbol; None = the module itself
    py_plain_import: bool = False  # `import a.b` binds `a`, not `a.b`


@dataclass
class FileAnalysis:
    refs: list[Ref] = field(default_factory=list)
    symbols: list[RepoSymbolRecord] = field(default_factory=list)
    diagnostics: list[RepoDiagnosticRecord] = field(default_factory=list)
    calls: list[CallSite] = field(default_factory=list)
    bindings: list[Binding] = field(default_factory=list)


class Analyzer(Protocol):
    """Adapter for one language family: write one and register it to add a language."""

    id: str
    languages: frozenset[str]

    def analyze(self, path: str, text: str) -> FileAnalysis: ...
