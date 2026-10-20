# ruff: noqa: E501
"""HTML and CSS references: scripts, stylesheets, images, @import and url()."""

from html.parser import HTMLParser

import tree_sitter_css as ts_css
from tree_sitter import Language, Node, Parser

from app.domain.records import RepoDiagnosticRecord
from app.explorer.analysis.base import FileAnalysis, Ref

HTML_SOURCE = "html.parser"
CSS_SOURCE = "tree-sitter.css"
_CSS = Language(ts_css.language())


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.refs: list[Ref] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): v for k, v in attrs if v is not None}
        line = self.getpos()[0]
        if tag == "script" and a.get("src"):
            self.refs.append(Ref(a["src"], "reference", line, note="script"))
        elif tag == "link" and a.get("href"):
            rel = a.get("rel", "").lower()
            note = "stylesheet" if "stylesheet" in rel else rel or "link"
            if "stylesheet" in rel or "icon" in rel or "preload" in rel or "modulepreload" in rel:
                self.refs.append(Ref(a["href"], "reference", line, note=note))
        elif tag in {"img", "source", "video", "audio", "iframe"} and a.get("src"):
            self.refs.append(Ref(a["src"], "reference", line, note=tag))


class HtmlAnalyzer:
    id = HTML_SOURCE
    languages = frozenset({"html"})

    def analyze(self, path: str, text: str) -> FileAnalysis:
        c = _Collector()
        try:
            c.feed(text)
            c.close()
        except Exception as e:  # html.parser is lenient, but never let one file stop the run
            return FileAnalysis(
                diagnostics=[
                    RepoDiagnosticRecord(
                        path=path, line=1, column=0, severity="warning", code="parse_failed",
                        message=f"Could not parse this HTML ({type(e).__name__})",
                        source=HTML_SOURCE,
                    )
                ]
            )  # fmt: skip
        return FileAnalysis(refs=c.refs)


def _css_string(n: Node) -> str:
    t = n.text.decode("utf-8", "replace") if n.text else ""
    return t.strip("'\"")


def _scan_urls(text: str) -> list[tuple[int, str, bool]]:
    """url(...) tokens by lexing, because the CSS grammar mis-parses unquoted `url(../x.png)`.

    Skips comments. Returns (line, value, preceded_by_@import_in_the_same_statement).
    """
    out: list[tuple[int, str, bool]] = []
    i, n, line = 0, len(text), 1
    stmt_start = 0
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end == -1 else end + 2
            line += text.count("\n", i, end)
            i = end
            continue
        elif c in ";{}":
            stmt_start = i + 1
        elif text[i : i + 4].lower() == "url(" and (
            i == 0 or not (text[i - 1].isalnum() or text[i - 1] in "-_")
        ):
            j = i + 4
            while j < n and text[j] in " \t\n":
                j += 1
            quote = text[j] if j < n and text[j] in "'\"" else ""
            if quote:
                j += 1
                k = text.find(quote, j)
            else:
                k = text.find(")", j)
            if k != -1:
                value = text[j:k].strip()
                if value:
                    is_import = text[stmt_start:i].strip().lower().startswith("@import")
                    out.append((line, value, is_import))
                i = k
                continue
        i += 1
    return out


class CssAnalyzer:
    id = CSS_SOURCE
    languages = frozenset({"css"})

    def analyze(self, path: str, text: str) -> FileAnalysis:
        out = FileAnalysis()
        tree = Parser(_CSS).parse(text.encode("utf-8"))
        stack = [tree.root_node]
        while stack:  # @import "file.css";  (quoted form; parsed reliably)
            n = stack.pop()
            if n.type == "import_statement":
                for c in n.named_children:
                    if c.type == "string_value":
                        out.refs.append(Ref(_css_string(c), "style_import", n.start_point[0] + 1))
                        break
                continue
            stack.extend(reversed(n.children))
        for line, value, is_import in _scan_urls(text):
            out.refs.append(
                Ref(
                    value,
                    "style_import" if is_import else "reference",
                    line,
                    note=None if is_import else "url()",
                )
            )
        out.refs.sort(key=lambda r: r.line)
        return out
