# Repository Explorer — audit and implementation plan (awaiting approval)

Date 2026-10-20. Base: `main@eba701c`, clean working tree, 21 commits. Nothing below is implemented yet.

## 1. What exists (verified by reading the tree today)
- **Graph:** one `ReactFlow` in `app/App.tsx` (@xyflow/react 12), one node type (`nodes/CodeNode.tsx`, multi-port for
  branching), default edges, `isValidConnection` (self-loop/cycle/duplicate), minimap above 12 nodes, `minZoom 0.1`.
  State, autosave, undo/redo and run status live in one 865-line Zustand store (`state/store.ts`).
- **Editor:** Monaco bundled locally (`editor/monaco-setup.ts`); used for Python code and JSON fields.
- **Backend:** layered FastAPI app (domain → engine → nodes/runtime → services → api; import-linter enforced), SQLite +
  Alembic (0001–0005), SSE events, run hub, execution gate, SSRF-guarded HTTP, keychain credentials, OpenAPI-generated TS types.
- **Desktop:** Tauri app with bundled Python runtime; dialog/fs plugins just added.
- **Gates (measured today):** ruff, format, mypy, import-linter, 280 backend tests (1 skipped), eslint, prettier, frontend tests all pass.

## 2. Does not exist
No GitHub/Git code, no repository/file/symbol/edge models, no language registry or parsers (no tree-sitter, no `ast`
usage outside the code runner), no auto-layout library, no file tree, no read-only multi-file editor, no HTML preview,
no test-discovery or approved-command runner, no AI provider integration. Sidebar/dock layout is fixed, not resizable.

## 3. Unverified / incomplete (existing)
Playwright e2e absent; CI workflow never run on GitHub; native window verified by logs/HTTP only; the node
styling is a single shape (no category visuals, no edge types/legend); `store.ts` is large and will need splitting
before a second graph mode is added.

## 4. Reuse vs new
Reuse: ReactFlow setup, `canvas/{graph,mapper}` patterns, Monaco setup, Zustand, Dialog/Menu/CommandPalette, SSE client,
Alembic/repository pattern, error envelope, security middleware, OpenAPI type generation, execution gate (for any
subprocess). New: `explorer/` backend package (acquire, index, analyze, graph), `ExplorerNode`/`DirectoryNode`/edge
components, `explorer` store slice, file tree, repo import screen, read-only file viewer, auto-layout (add `@dagrejs/dagre`
or ELK — the only new graph dependency, a layout algorithm, not a second renderer).

## 5. Key design decisions (please confirm)
1. **Acquisition:** GitHub REST API (tree at a commit SHA + raw blob fetch), public repos only first, optional token later via
   keychain. Alternative: shallow `git clone`/tarball (more complete, but archive-extraction risks and larger downloads).
   *Recommend REST + tarball-free* with file-count/size caps; tarball only if rate limits bite.
2. **Analysis runs in the backend, never executes repo code.** Python via stdlib `ast`; JS/TS/CSS/HTML via tree-sitter
   (`tree-sitter` + grammars as Python deps, bundled in the desktop runtime) — adds native wheels, I will verify they install
   in the bundled runtime before committing to them. Regex only as labelled "heuristic" fallback.
3. **Data model (new migration 0006):** `repo_revisions` (owner, repo, commit_sha, branch, status, counts, schema_version),
   `repo_files` (revision_id, path, language, size, lines, sha, analysis_status), `repo_edges` (src, dst|null, kind,
   confidence: syntactic|resolved|unresolved|heuristic, line), `repo_symbols`, `repo_diagnostics`. File *contents* are cached
   on disk by blob SHA, not in SQLite. Every graph is keyed by commit SHA; refresh creates a new revision.
4. **Semantics:** explorer edges are visually distinct (dashed/neutral, labelled by kind, legend), carry provenance, never
   animate; repo nodes are not executable and cannot be dropped into Build workflows (R8 does explicit, reviewed conversion).
5. **Scale:** server returns a directory-collapsed graph; clients expand a directory on demand; search-first; hard cap on
   rendered nodes (e.g. 300) with a visible notice; layout computed once per expansion.
6. **Security:** host/URL allowlist (`github.com`, `api.github.com`, `raw.githubusercontent.com`/blobs), no redirects off
   GitHub, size/count/time caps, path normalisation (reject `..`, absolute, symlink-like entries), binary detection,
   source shown as text only (React escapes), HTML preview in a `sandbox=""` iframe with `srcdoc` and CSP `default-src 'none'`,
   no token in URLs/logs, nothing executed on import. Commands/tests (R6) run only after an explicit per-command approval via the
   existing execution gate, in a scratch checkout, never inside the app data dir.
7. **AI:** off by default; no provider is configured today. Deferred to after R6 and only with explicit opt-in.

## 6. Milestones and acceptance
| # | Scope | Acceptance (all verified by tests and a real run) |
|---|---|---|
| R1 | This audit (done) | Plan approved |
| R2 | URL validation, acquisition at a pinned SHA, tree index, persistence, file tree UI, read-only viewer, import screen with progress/errors | A real public repo imports; paths/SHA match GitHub; invalid URL, 404, rate-limit, oversize each show a distinct error; re-import of same SHA hits cache; no network call outside GitHub hosts (tested with a fake transport) |
| R3 | Mode switch (Build / Explorer), `ExplorerNode`, directory nodes, curved edges, legend, dagre layout, search-focus, filters | 300-node repo renders and pans smoothly (measured); Build mode regression tests unchanged and green |
| R4 | Analyzer interface + Python and JS/TS analyzers (imports, symbols), later HTML/CSS/JSON/YAML refs; edges with confidence/provenance | Fixture repos with known import graphs produce exactly the expected edges; dynamic imports are reported unresolved, not invented |
| R5 | Inspector for file/edge, symbol navigation, diagnostics to line, language registry, safe HTML preview | Clicking node/edge/diagnostic opens correct file+line; preview cannot reach parent origin (tested) |
| R6 | Test discovery, proposed patches with diff, approval-gated command runner | Nothing runs without approval; cancel kills process tree; patch never applied silently |
| R7 | Large-repo hardening, cancellation of stale jobs, perf measurements, e2e (Playwright) | Measured numbers recorded, not promised |
| R8 | Explicit "create workflow from selection" with provenance | Generated nodes labelled wrapper/function/copy; user reviews before save |

Each milestone ends with a report: files changed, tests actually run, limitations, next step. Desktop rebuild is checked at R3
and R7. Estimated size: R2–R5 are the bulk; R6–R8 are separable follow-ups.

## 7. Honest risks
GitHub unauthenticated rate limit is 60 requests/hour, so per-file blob fetching will hit it quickly: acquisition must use the
tarball/zipball endpoint (one request) or require a token. I therefore now recommend **tarball download with safe in-memory
extraction** (cap entries/size, reject unsafe paths and links) over per-blob REST. Tree-sitter wheels in the bundled runtime are
unverified. Static analysis will miss dynamic imports and generated code; the UI will say so. Private repos are out of scope until a
keychain-backed token flow is built.

## R2 status (2026-10-20): implemented
Backend `app/explorer/` (URL allowlist parser, GitHub client limited to `api.github.com`/`codeload.github.com` with a
redirect budget, safe tarball extraction with file-count/size/total limits, language detection), `services/explorer_service.py`
(pinned-commit imports as background tasks, cancel, cache by commit, read only indexed paths), migration 0006
(`repo_revisions`, `repo_files`), API `/api/v1/explorer/*`. Frontend: Build/Explorer switch, import form with *Show Nodes*,
progress, repository card, searchable file tree, read-only Monaco viewer. Not in R2: the graph (R3), dependency analysis (R4),
symlinks are skipped (counted in neither total), private repositories, token support.
Verified against real GitHub: `psf/requests@611c616` imported 128 files = GitHub's 130 blobs minus 2 symlinks.
