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

**Known limits.** No call graph, no type information, no tsconfig/webpack alias resolution, no Python namespace-package or `sys.path`
manipulation, `url()` in CSS is lexed because the grammar mis-parses unquoted relative URLs, JSON/YAML/SQL/shell are indexed but not analysed,
and tree-sitter may report newer syntax as an error (reported as a warning, not an error).
