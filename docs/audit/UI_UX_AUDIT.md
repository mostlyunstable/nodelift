# UI / UX audit and design direction

Audit date 2026-10-18. **Inspection method:** I drove the real UI (`localhost:5173`, dev build) in the in-app browser
at 810×992 (a narrow pane) and ~1024×768, took screenshots, and read the components. I did **not** test other
browsers, high-DPI, light mode (none exists), screen readers, or touch. Findings marked *(source)* come from reading
code, not from viewing.

## 1. What the UI is today
One screen, three regions: a 44 px toolbar; a split workspace (canvas | 440 px inspector); a 280 px bottom dock with
three fixed columns (workflow input · run history/events/steps · node execution). Dark only, system sans + mono,
a single set of CSS variables in `app/styles.css` (69 lines). It is a coherent prototype, not yet a product.

## 2. Findings by area

### A. Visual identity
| Where | Problem | Proposal | Why it matters |
|---|---|---|---|
| `styles.css` | Variables exist (`--bg --panel --border --accent --ok --bad --skip`) but are not a system: no type scale, spacing scale, elevation or radius tokens; sizes are literals (`font-size:12px/13px/11px`, `padding:5px 12px`) | Adopt the token set in §4 and replace literals | Consistency and effort to add themes later |
| All text | One system font; hierarchy comes from size only; uppercase micro-labels (`h4`) everywhere | Inter (UI) + a code font; 4 text styles; reserve uppercase for dock tab labels only | Reads like an admin template today |
| Buttons (`App.tsx`) | `+ Add node`, Validate, Run, Cancel, Save, Publish, Open, New all look alike except Run (green) | Primary = Run only; secondary = ghost; destructive = confirm dialog | Users can't see what matters |
| Theme | Dark only; no `prefers-color-scheme` | Light theme from the same tokens | Accessibility, daylight use |
| Motion | Only a pulse on running nodes (good, purposeful) | Keep; add 120 ms panel/hover transitions; honour `prefers-reduced-motion` | Feedback without noise |

### B. Workflow canvas (`App.tsx`, `CodeNode.tsx`)
| Problem | Evidence | Proposal |
|---|---|---|
| Empty canvas is blank dots plus a miniature of nothing | screenshot: empty minimap box, no hint | Empty state with 3 actions: *Start from the "Debug me" example*, *Add a node*, *Open workflow* (⌘K hint) |
| Canvas is squeezed to ~365 px at 800 px width because the inspector is a fixed 440 px | screenshot | Inspector min 320/max 40%; collapsible; resizable split; dock collapsible |
| Nodes: one shape, name + `code.python` string (raw type id as subtitle) | `CodeNode.tsx` | Icon chip by category, human title, one-line summary (first line of code / URL / mapping keys), status ring; ports labelled on hover |
| Connection feedback: none; self-loops/cycles can be drawn, rejected only at run/validate | `store.onConnect`; `isValidConnection` absent *(source)* | `isValidConnection` blocks self-loops and cycles with a tooltip reason |
| Delete, copy/paste, multi-select, align, undo/redo | no handlers; delete relies on RF default *(source)* | Undo/redo stack in the editor store; ⌘C/⌘V/⌘D; Delete confirm only for >1 node |
| Minimap always on | screenshot | Hide below ~12 nodes or make toggleable |
| Large graphs | measured: 300 nodes open in ~190 ms, select in ~30 ms (dev) — fine; but >200 nodes cannot run (`MAX_NODES`) and nothing warns | Show node count with a limit warning; consider collapsing/grouping later |

### C. Debugging experience (`RunPanel.tsx`, `ResultView.tsx`)
Strengths: live per-node status on the canvas, an event timeline, per-node input/output/logs/error with durations,
resume. Gaps:
| Problem | Proposal |
|---|---|
| An error does not take you to the cause: failing node isn't auto-selected; traceback line isn't mapped to the editor | On `run.finished` with a failure: select the first failed node, open its tab, add a Monaco marker at the traceback line (parse `File "<node>", line N`) |
| Run history shows `v1 failed 46ms · 16:47:16` — the time is wrong (UTC treated as local, BUG-1), no input, no version link | Fix timestamps; show relative time, trigger input preview, and *Open this version* |
| Validate results are a small red list in the bottom-left column | A *Problems* tab with click-to-select-node (VS Code style) and badges on offending nodes |
| Logs only after the node ends; no search | Logs tab (stdout/stderr, filter, copy); stream when the runtime supports it |
| No way to re-run with the same input, or compare two runs | *Re-run*, *Re-run from this node* (already supported by resume), later run diff |
| Skipped vs failed vs cancelled distinguished only by colour | Add icons/labels; don't rely on colour alone |

### D. Information architecture
Today: everything on one screen, workflows reachable only through an `Open…` dropdown in the toolbar (clipped below
~900 px — at 810 px the `Open…` select and *New* were absent from the accessibility tree).
Proposed layout (VS Code-like, restrained):
- **Left rail** (collapsible): Workflows, Node library with search, Runs.
- **Center:** canvas with a floating run bar (Run ▸ / Stop, status, elapsed).
- **Right inspector** with tabs: *Config* · *Code* · *Test*.
- **Bottom dock** tabs: *Run* · *Events* · *Logs* · *Problems*.
- **⌘K command palette:** run, add node (fuzzy), open workflow, go to node, toggle panels, export.
- Settings and Diagnostics as a dialog, not a pane.
Shortcuts: ⌘↩ run, ⌘. stop, ⌘S save, ⌘K palette, ⌘Z/⇧⌘Z, ⌘D duplicate, ⌘F node search.

### E. Product polish
| Problem | Evidence | Fix |
|---|---|---|
| **Unsaved work is invisible and lost on reload** | measured: add node, reload → blank canvas, no prompt | Dirty dot next to the name, autosave drafts (debounced, to the server), restore last workflow on launch, confirm on *New*/*Open* |
| *Publish* is unexplained and mostly redundant (runs auto-snapshot) | `App.tsx`, `workflow_service.snapshot` | Rename to *Save version…* with a note field, or hide until a version browser exists |
| Versions invisible | `listVersions` only feeds the button label | Version list with view / diff / restore |
| Loading/empty/error/offline states | one `message` string rendered in the bottom-left; backend down → silent | Toast system + a global *Backend unreachable* banner with retry |
| Accessibility | only 4 `aria-*`/`role` occurrences in the whole UI; no `:focus-visible` styles; status by colour | Visible focus ring, labelled controls, `aria-live` for run status, keyboard-operable canvas, 4.5:1 contrast audit |
| Responsive | toolbar `overflow-x:auto` hides controls; fixed pane sizes | Collapse secondary actions into a menu below 1000 px |
| Onboarding | none | §5 |
| Monaco requires internet | CDN loader (measured string in bundle) | Bundle locally (also a desktop prerequisite) |
| Run input field | "Workflow input (JSON)" sits in the dock, easy to miss; invalid JSON shown as a bottom message | Move into the run bar popover with inline validation |

## 3. Design principles
1. **Show what happened.** Execution state is the primary content; chrome recedes.
2. **One accent.** Colour carries state, not decoration.
3. **Code first, visual second.** The editor and the test loop are as fast as a REPL.
4. **Never lose work.** Autosave, dirty state, undo, versions.
5. **Honest about risk.** Trusted-mode and network limits are visible where they apply.
6. **Keyboard-complete.** Everything reachable from ⌘K.

## 4. Design system (proposal)

**Typography.** UI: Inter (or system-ui fallback), 13 px body / 12 px secondary / 11 px captions / 15 px panel titles /
20 px headings. Code and data: JetBrains Mono (or SF Mono) 12.5 px. Line height 1.45 for text, 1.5 for code.
**Spacing.** 4 px base: 4 · 8 · 12 · 16 · 24 · 32. Panel padding 12; dense lists 6/8.
**Radius & elevation.** Radius 6 (controls), 8 (cards/nodes), 12 (dialogs). Surfaces:
`--bg` (canvas) < `--surface` (panels) < `--raised` (menus, popovers) < `--overlay` (dialogs); borders carry hierarchy,
shadow only on popovers/dialogs.
**Semantic tokens** (dark/light pairs resolved in CSS, never hard-coded in components):
`--text`, `--text-muted`, `--text-faint`, `--border`, `--border-strong`, `--accent`, `--accent-fg`, `--focus`,
`--success`, `--danger`, `--warning`, `--info`, `--neutral`, each with a `-bg` tint for pills/rows.
**Status indicators.** Icon + label + colour: running (accent, pulse), succeeded (success, ✓), failed (danger, ✕),
skipped (neutral, ⤼), cancelled (neutral, ⏹), retrying (warning, ↻). Never colour alone.
**Node-type colour strategy.** The accent is reserved for selection and running. Categories get a *small* chip only
(icon on a 12 % tint): Code, Data (transform), Integrations (HTTP), plus one slot for plugins. Node bodies stay neutral
so status colours remain readable.
**Components.** Buttons: primary (Run only), secondary, ghost, danger; sizes 24/28/32. Inputs share one height, focus
ring 2 px `--focus` with 2 px offset. Tabs, toasts, dialogs, menus from one primitive set (e.g. Radix) rather than
bespoke CSS.
**Motion.** 120 ms ease-out for hover/focus, 200 ms for panels, pulse only for running; disabled under
`prefers-reduced-motion`.
**Accessibility requirements.** WCAG AA contrast, visible focus everywhere, keyboard path for every action, status
announced via `aria-live`, no information by colour alone, 24 px minimum targets.

## 5. First-session experience (target: first successful run < 3 minutes, first debugged error < 5)
1. First launch → empty state offers **"Try the Debug-me example"** (also in the Help menu).
2. The example is 4 nodes: *Make data* (code) → *Transform* (JSON transform) → *Divide* (code with a deliberate
   `1 / 0`) → *Report*. A one-line coach mark per step ("Press ⌘↩ to run").
3. Run → nodes light up in sequence; *Divide* fails, the app auto-selects it, opens *Code* with the failing line marked
   and shows the input it received and the traceback in plain language ("ZeroDivisionError on line 3. The input had
   `count: 0`").
4. User edits `1 / 0` → `1 / max(count, 1)`, presses ⌘↩; **Resume from failure** reuses the finished nodes — the app
   explains that the first two nodes were not re-run.
5. Completion nudge: *Save as workflow*, *Add an HTTP node*, *Browse the node library (⌘K)*.
Needed capabilities: example template, auto-select failing node, traceback→line markers, plain-language error
summary, coach marks. Resume already exists.

## 6. What to build vs defer
| Feature | Verdict |
|---|---|
| Autosave + dirty state, undo/redo, connection validation | **Now** (trust) |
| Error→node/line navigation, Problems and Logs tabs | **Now** (the differentiator) |
| Command palette + node search | **Soon** (cheap, high leverage) |
| Version browser/diff, run comparison | **Soon** |
| Templates/onboarding | **Soon** (first-run) |
| Workflow import/export | After format migrations exist |
| Subflows, breakpoints/step-through, scheduling, credentials UI | Later (credentials before any real API use) |
