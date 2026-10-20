from app.explorer.analysis.base import Analyzer
from app.explorer.analysis.javascript import JavaScriptAnalyzer
from app.explorer.analysis.others import (
    GoAnalyzer,
    JavaAnalyzer,
    JsonAnalyzer,
    MarkdownAnalyzer,
    RubyAnalyzer,
    RustAnalyzer,
    ShellAnalyzer,
    SqlAnalyzer,
    YamlAnalyzer,
)
from app.explorer.analysis.python import PythonAnalyzer
from app.explorer.analysis.web import CssAnalyzer, HtmlAnalyzer


def default_analyzers() -> dict[str, Analyzer]:
    """language id -> analyzer. Languages not listed are browsable but not analysed."""
    out: dict[str, Analyzer] = {}
    for a in (
        PythonAnalyzer(),
        JavaScriptAnalyzer(),
        HtmlAnalyzer(),
        CssAnalyzer(),
        GoAnalyzer(),
        JavaAnalyzer(),
        RustAnalyzer(),
        RubyAnalyzer(),
        ShellAnalyzer(),
        MarkdownAnalyzer(),
        YamlAnalyzer(),
        JsonAnalyzer(),
        SqlAnalyzer(),
    ):
        for lang in a.languages:
            out[lang] = a
    return out
