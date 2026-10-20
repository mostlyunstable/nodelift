# 0009 — Static dependency analysis with explicit confidence

**Status:** accepted (R4)

**Decision.** Repository files are parsed, never imported or executed. Python uses the standard-library `ast`; JavaScript/TypeScript and
CSS use tree-sitter; HTML uses `html.parser`. Each language is an `Analyzer` adapter (`app/explorer/analysis`) that returns
references exactly as written; one `Resolver` maps them to files that exist in the indexed revision.
Every relation records `confidence` (`resolved`, `heuristic`, `unresolved`, `external`), the analyzer that produced it, the line, the raw
specifier and a note (for example "optional (inside try/except)", "type-checking only", "path alias, config not applied").

**Never invented.** Dynamic imports with computed targets are `unresolved` and have no destination. Imports of packages that are not in the
repository are `external` and are not drawn between files. Test-to-source links by file name are `heuristic` and only added when no
real import already links the pair.

**Languages (2026-10-20).** Python, JavaScript/TypeScript, HTML, CSS, Go (`go.mod` module paths; a package import links to the package's
non-test files), Java (import to file by package path), Rust (`mod` declarations, `crate::` paths), Ruby (`require`, `require_relative`), shell
(`source`, `. file`, `bash x.sh`; heuristic because the base folder is the run-time working directory), Markdown (links and images, headings as symbols),
YAML (path-valued keys such as GitHub Actions `uses: ./...`, `env_file`, `build`), JSON (`main`/`types`/`$ref` paths, syntax errors), SQL via sqlglot
(CREATE as symbols; a table used in one file is linked to the single CREATE in another by name only, heuristic). C#, PHP, Kotlin, Swift, C/C++ are
shown but not analysed.

**Known limits.** No call graph, no type information, no tsconfig/webpack alias resolution, no Python namespace-package or `sys.path`
manipulation, `url()` in CSS is lexed because the grammar mis-parses unquoted relative URLs, JSON/YAML/SQL/shell are indexed but not analysed,
and tree-sitter may report newer syntax as an error (reported as a warning, not an error).
