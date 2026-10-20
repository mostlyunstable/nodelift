# 0012 — The Explorer draws folders as nested cards, and draws lines only when asked

**Status:** accepted (supersedes the left-to-right tree of R3)

**Problem.** A repository drawn as a tree with one edge per folder-contains-item and every dependency line at once becomes a very long
strip of boxes joined by a tangle of lines. Real users could not scan it (Flask: a 6 %-zoom sliver; React: worse).

**Decision.**
- *Containment is nesting.* A folder is a titled **card**; its files are equal-sized **tiles** in a small grid inside it; a collapsed
  folder is a dashed tile that opens into a card; sub-folders are cards inside the parent, packed in shelves (tallest first) so the
  whole map stays roughly landscape. No lines are spent on "contains".
- *Lines are dependencies only, and only on demand.* Default **Selected file** (what it imports, what imports it, in two colours);
  **Folders** (the 40 strongest links between top-level items, counted); **All** (capped at 600); **Off**.
- Nothing can be dragged out of place, so the layout is always tidy; the view opens at a readable zoom on the whole card (or the top
  of it, when the map is too big to read at once) and brings a folder you open into view.
- Layout is a pure function (`explorer/graph.ts`): tests assert no overlaps, every child inside its card, a landscape aspect for flat,
  grouped, deep and mixed repositories, and a compact block for a 60-file folder.

**Consequences.** Big repositories are still big on screen (Flask's code-only map is ~1750×1900 px at zoom 1); search, the minimap and
the file list are the way to jump. The old per-edge "folder contains file" line type no longer exists.
