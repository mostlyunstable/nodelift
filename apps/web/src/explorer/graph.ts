import type { Edge, Node } from '@xyflow/react'
import type { RepoDiagnostic, RepoEdge, RepoFile } from '../api/client'
import { buildTree, type TreeDir } from './tree'

// ---- sizes (px). Every file and collapsed folder is one tile of the same size, so the map reads like a grid.
export const TILE_W = 184
export const TILE_H = 46
export const FILE_W = TILE_W // kept for older imports
const GAP = 10
const PAD = 14
const HEADER_H = 38
const SHELF_GAP = 14

export const DEFAULT_CAP = 300
/** Nodes drawn when a repository first opens: enough to orient yourself, few enough to read. */
export const INITIAL_CAP = 120
export const DEFAULT_DEP_CAP = 600
const MAX_RELATIONS_PER_EDGE = 40

/** Languages whose files are source code, as opposed to docs, configuration or data. */
export const CODE_LANGUAGES = new Set([
  'python', 'javascript', 'typescript', 'go', 'java', 'rust', 'ruby', 'shell', 'html', 'css',
  'scss', 'less', 'sql', 'c', 'cpp', 'csharp', 'php', 'swift', 'kotlin',
]) // prettier-ignore

export const isCode = (f: RepoFile): boolean => CODE_LANGUAGES.has(f.language) && f.stored

/** Big repositories open showing code only; small ones show every file. */
export const shouldDefaultToCodeOnly = (files: RepoFile[]): boolean =>
  files.length > 60 && files.filter(isCode).length >= 5

/**
 * A folder is a card that contains its files; sub-folders are cards inside it. A collapsed folder is a tile you can open.
 * Nothing is drawn between them: containment is shown by nesting, so the lines on screen are only dependencies.
 */
export type NodeKind = 'file' | 'folder' | 'card'
export interface GraphNodeData extends Record<string, unknown> {
  kind: NodeKind
  name: string
  path: string
  count: number // files under a folder (after filtering)
  expanded: boolean
  language: string
  lines: number
  size: number
  note: string | null // why a file has no readable source
  problems: number // diagnostics found in the file (or under a folder)
  width: number
  height: number
}
export type ExplorerNode = Node<GraphNodeData, NodeKind>

/** `dependency`: something static analysis found, with a confidence and the exact relations behind it. */
export type EdgeKind = 'dependency'
export type EdgeDirection = 'out' | 'in' | ''
export interface ExplorerEdgeData extends Record<string, unknown> {
  kind: EdgeKind
  from: string
  to: string
  relations: RepoEdge[] // what was found (capped)
  count: number // how many relations this drawn edge stands for
  aggregated: boolean // an endpoint is a folder standing in for its files
  confidence: 'resolved' | 'heuristic'
  direction: EdgeDirection // relative to the selected file, when there is one
}
export type ExplorerEdge = Edge<ExplorerEdgeData, EdgeKind>

/** Which lines to draw. Drawing every one at once is what makes big graphs unreadable. */
export type DepMode = 'off' | 'selected' | 'folders' | 'all'

export interface GraphOptions {
  expanded: ReadonlySet<string> // folder paths; '' is the repository root
  languages: ReadonlySet<string> // empty = every language
  codeOnly?: boolean // hide documentation, config and data files
  cap?: number
  dependencies?: RepoEdge[] // file-to-file relations from analysis
  diagnostics?: RepoDiagnostic[]
  dependencyCap?: number
  depMode?: DepMode
  selectedPath?: string | null
}

export interface BuiltGraph {
  nodes: ExplorerNode[]
  edges: ExplorerEdge[]
  truncated: boolean
  hiddenNodes: number
  matchingFiles: number
  dependencyEdges: number // drawn
  hiddenDependencyEdges: number
  size: { width: number; height: number } // of the root card
}

export const fileId = (path: string) => `f:${path}`
export const dirId = (path: string) => `d:${path}`

/** The folders that must be open for `path` to be visible: the root and every parent. */
export function ancestorDirs(path: string): string[] {
  const parts = path.split('/').slice(0, -1)
  return ['', ...parts.map((_, i) => parts.slice(0, i + 1).join('/'))]
}

function noteFor(f: RepoFile): string | null {
  if (f.stored) return null
  return f.skip_reason === 'too_large' ? 'too large' : f.skip_reason === 'not_utf8' ? 'not UTF-8' : 'binary'
}

// ---- layout ---------------------------------------------------------------------------------------------

interface Card {
  dir: TreeDir
  name: string
  tiles: { id: string; kind: 'file' | 'folder'; ref: TreeDir | RepoFile }[] // folders (collapsed) first, then files
  cards: Card[] // expanded sub-folders
  w: number
  h: number
  gridCols: number
  gridH: number
  shelves: { x: number; y: number; card: Card }[]
}

/** Columns for `n` tiles so a card is a little wider than tall. */
const columnsFor = (n: number): number => Math.max(1, Math.min(5, Math.round(Math.sqrt(n * 1.7))))

function measure(card: Card): void {
  const n = card.tiles.length
  card.gridCols = n === 0 ? 0 : columnsFor(n)
  const rows = n === 0 ? 0 : Math.ceil(n / card.gridCols)
  const gridW = card.gridCols === 0 ? 0 : card.gridCols * TILE_W + (card.gridCols - 1) * GAP
  card.gridH = rows === 0 ? 0 : rows * TILE_H + (rows - 1) * GAP
  for (const c of card.cards) measure(c)

  // Sub-folder cards go in shelves: tallest first, rows no wider than about the square root of their total area.
  const kids = [...card.cards].sort((a, b) => b.h - a.h || a.name.localeCompare(b.name))
  const area = kids.reduce((s, k) => s + k.w * k.h, 0)
  const widest = kids.reduce((m, k) => Math.max(m, k.w), 0)
  const target = Math.max(gridW, widest, Math.sqrt(area * 1.6))
  card.shelves = []
  let x = 0
  let y = 0
  let rowH = 0
  let shelfW = 0
  for (const k of kids) {
    if (x > 0 && x + k.w > target) {
      y += rowH + SHELF_GAP
      x = 0
      rowH = 0
    }
    card.shelves.push({ x, y, card: k })
    x += k.w + SHELF_GAP
    rowH = Math.max(rowH, k.h)
    shelfW = Math.max(shelfW, x - SHELF_GAP)
  }
  const shelfH = kids.length === 0 ? 0 : y + rowH
  const contentW = Math.max(gridW, shelfW, TILE_W)
  const contentH = card.gridH + (card.gridH > 0 && shelfH > 0 ? SHELF_GAP : 0) + shelfH
  card.w = contentW + PAD * 2
  card.h = HEADER_H + contentH + PAD
}

// ---- build ---------------------------------------------------------------------------------------------

export function buildGraph(files: RepoFile[], repoName: string, opts: GraphOptions): BuiltGraph {
  const cap = opts.cap ?? DEFAULT_CAP
  const keep = (f: RepoFile) =>
    (opts.languages.size === 0 || opts.languages.has(f.language)) && (!opts.codeOnly || isCode(f))
  const root = buildTree(files.filter(keep))
  const problemsByPath = new Map<string, number>()
  for (const d of opts.diagnostics ?? []) {
    if (d.severity === 'info') continue // notes (parser limits, build-output imports) are not problems
    problemsByPath.set(d.path, (problemsByPath.get(d.path) ?? 0) + 1)
  }
  const problemsUnder = (path: string): number => {
    const prefix = path === '' ? '' : `${path}/`
    let total = 0
    for (const [p, c] of problemsByPath) if (p.startsWith(prefix)) total += c
    return total
  }

  // 1. which folders open into cards, within the node budget
  let used = 0
  let hidden = 0
  const makeCard = (dir: TreeDir, name: string): Card => {
    used++ // the card itself
    const card: Card = { dir, name, tiles: [], cards: [], w: 0, h: 0, gridCols: 0, gridH: 0, shelves: [] }
    const subdirs = dir.children.filter((c): c is TreeDir => c.kind === 'dir')
    const fileKids = dir.children.filter((c) => c.kind === 'file')
    for (const d of subdirs) {
      if (opts.expanded.has(d.path) && used < cap) card.cards.push(makeCard(d, d.name))
      else if (used < cap) {
        used++
        card.tiles.push({ id: dirId(d.path), kind: 'folder', ref: d })
      } else hidden += 1 + d.fileCount
    }
    for (const f of fileKids) {
      if (used < cap) {
        used++
        card.tiles.push({ id: fileId(f.path), kind: 'file', ref: (f as { file: RepoFile }).file })
      } else hidden++
    }
    return card
  }
  const rootCard = makeCard(root, repoName)
  measure(rootCard)

  // 2. nodes, positioned relative to their parent card
  const nodes: ExplorerNode[] = []
  const emit = (card: Card, x: number, y: number, parentId?: string) => {
    const id = dirId(card.dir.path)
    nodes.push({
      id,
      type: 'card',
      position: { x, y },
      ...(parentId ? { parentId } : {}),
      draggable: false,
      selectable: false,
      width: card.w,
      height: card.h,
      style: { width: card.w, height: card.h },
      zIndex: 0,
      data: {
        kind: 'card', name: card.name, path: card.dir.path, count: card.dir.fileCount, expanded: true,
        language: '', lines: 0, size: 0, note: null, problems: problemsUnder(card.dir.path),
        width: card.w, height: card.h,
      },
    }) // prettier-ignore
    card.tiles.forEach((t, i) => {
      const col = i % card.gridCols
      const row = Math.floor(i / card.gridCols)
      const pos = { x: PAD + col * (TILE_W + GAP), y: HEADER_H + row * (TILE_H + GAP) }
      if (t.kind === 'folder') {
        const d = t.ref as TreeDir
        nodes.push({
          id: t.id, type: 'folder', position: pos, parentId: id, draggable: false, selectable: false,
          width: TILE_W, height: TILE_H,
          style: { width: TILE_W, height: TILE_H },
          data: {
            kind: 'folder', name: d.name, path: d.path, count: d.fileCount, expanded: false, language: '',
            lines: 0, size: 0, note: null, problems: problemsUnder(d.path), width: TILE_W, height: TILE_H,
          },
        }) // prettier-ignore
      } else {
        const f = t.ref as RepoFile
        const name = f.path.slice(f.path.lastIndexOf('/') + 1)
        nodes.push({
          id: t.id, type: 'file', position: pos, parentId: id, draggable: false, selectable: false,
          width: TILE_W, height: TILE_H,
          style: { width: TILE_W, height: TILE_H },
          data: {
            kind: 'file', name, path: f.path, count: 0, expanded: false, language: f.language, lines: f.lines,
            size: f.size, note: noteFor(f), problems: problemsByPath.get(f.path) ?? 0, width: TILE_W, height: TILE_H,
          },
        }) // prettier-ignore
      }
    })
    const shelfTop = HEADER_H + card.gridH + (card.gridH > 0 && card.shelves.length > 0 ? SHELF_GAP : 0)
    for (const s of card.shelves) emit(s.card, PAD + s.x, shelfTop + s.y, id)
  }
  emit(rootCard, 0, 0)

  // 3. dependency lines, only as many as can be read
  const dep = buildDependencyEdges(nodes, opts)
  return {
    nodes,
    edges: dep.edges,
    truncated: hidden > 0,
    hiddenNodes: hidden,
    matchingFiles: root.fileCount,
    dependencyEdges: dep.edges.length,
    hiddenDependencyEdges: dep.hidden,
    size: { width: rootCard.w, height: rootCard.h },
  }
}

/**
 * The visible node standing for `path`: its tile, or the collapsed folder tile hiding it. A file that is missing from an
 * *open* folder was filtered out, capped or does not exist: no owner. In `top` mode every file maps to the root-level
 * item (tile or card) that contains it, for a folder-to-folder overview.
 */
function ownerOf(path: string, byId: ReadonlyMap<string, ExplorerNode>, top: boolean): string | null {
  const parts = path.split('/')
  if (top) {
    const first = parts.length === 1 ? fileId(path) : dirId(parts[0]!)
    if (byId.has(first)) return first
    return parts.length > 1 && byId.has(fileId(path)) ? first : null
  }
  if (byId.has(fileId(path))) return fileId(path)
  const dirs = parts.slice(0, -1)
  for (let i = dirs.length; i >= 1; i--) {
    const id = dirId(dirs.slice(0, i).join('/'))
    const n = byId.get(id)
    if (n) return n.type === 'card' ? null : id
  }
  return null
}

function buildDependencyEdges(
  nodes: ExplorerNode[],
  opts: GraphOptions,
): { edges: ExplorerEdge[]; hidden: number } {
  const mode = opts.depMode ?? 'all'
  const relations = (opts.dependencies ?? []).filter((r) => r.dst !== null && r.dst !== undefined)
  if (mode === 'off' || relations.length === 0) return { edges: [], hidden: 0 }
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const sel = opts.selectedPath ?? null
  const top = mode === 'folders'
  const groups = new Map<string, ExplorerEdge>()
  for (const r of relations) {
    const src = r.src
    const dst = r.dst as string
    if (mode === 'selected' && (sel === null || (src !== sel && dst !== sel))) continue
    const a = ownerOf(src, byId, top)
    const b = ownerOf(dst, byId, top)
    if (a === null || b === null || a === b) continue
    const id = `x:${a}>${b}`
    let e = groups.get(id)
    if (!e) {
      e = {
        id, source: a, target: b, type: 'dependency', focusable: false,
        data: {
          kind: 'dependency', from: a, to: b, relations: [], count: 0, confidence: 'heuristic',
          aggregated: a !== fileId(src) || b !== fileId(dst), direction: mode === 'selected' ? (src === sel ? 'out' : 'in') : '',
        },
      } // prettier-ignore
      groups.set(id, e)
    }
    const d = e.data!
    d.count++
    if (d.relations.length < MAX_RELATIONS_PER_EDGE) d.relations.push(r)
    if (r.confidence === 'resolved') d.confidence = 'resolved'
    if (a !== fileId(src) || b !== fileId(dst)) d.aggregated = true
  }
  const all = [...groups.values()]
  if (top) all.sort((x, y) => (y.data?.count ?? 0) - (x.data?.count ?? 0)) // the strongest links first
  const cap = mode === 'all' ? (opts.dependencyCap ?? DEFAULT_DEP_CAP) : mode === 'folders' ? 40 : 200
  return { edges: all.slice(0, cap), hidden: Math.max(0, all.length - cap) }
}

/** Languages present, most common first, for the filter chips. */
export function languageCounts(files: RepoFile[]): [string, number][] {
  const m = new Map<string, number>()
  for (const f of files) m.set(f.language, (m.get(f.language) ?? 0) + 1)
  return [...m.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
}

/**
 * Folders to open when a repository first appears, so its files are already nodes: open level by level,
 * folders that hold code before folders that don't, then smaller before larger, until the node budget is used.
 */
export function defaultExpanded(files: RepoFile[], cap = INITIAL_CAP, codeOnly = false): Set<string> {
  const root = buildTree(codeOnly ? files.filter(isCode) : files)
  const codeIn = new Map<string, number>()
  for (const f of files)
    if (isCode(f)) for (const d of ancestorDirs(f.path)) codeIn.set(d, (codeIn.get(d) ?? 0) + 1)
  const open = new Set([''])
  let total = 1 + root.children.length
  let frontier = root.children.filter((c): c is TreeDir => c.kind === 'dir')
  while (frontier.length > 0) {
    frontier.sort(
      (a, b) =>
        Number((codeIn.get(a.path) ?? 0) === 0) - Number((codeIn.get(b.path) ?? 0) === 0) ||
        a.children.length - b.children.length,
    )
    const next: TreeDir[] = []
    for (const d of frontier) {
      if (total + d.children.length > cap) continue
      open.add(d.path)
      total += d.children.length
      next.push(...d.children.filter((c): c is TreeDir => c.kind === 'dir'))
    }
    frontier = next
  }
  return open
}

/** Every folder path, for "Expand all". The node cap still applies when drawing. */
export function allDirs(files: RepoFile[]): Set<string> {
  const out = new Set([''])
  for (const f of files) for (const d of ancestorDirs(f.path)) out.add(d)
  return out
}

export interface Rect {
  x: number
  y: number
  width: number
  height: number
}

/** Absolute position of a node (positions are relative to the parent card). */
export function absoluteRect(nodes: ExplorerNode[], id: string): Rect | null {
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const n = byId.get(id)
  if (!n) return null
  let x = n.position.x
  let y = n.position.y
  for (
    let p = n.parentId ? byId.get(n.parentId) : undefined;
    p;
    p = p.parentId ? byId.get(p.parentId) : undefined
  ) {
    x += p.position.x
    y += p.position.y
  }
  return { x, y, width: n.data.width, height: n.data.height }
}

/**
 * A pan/zoom that shows `rect` in a `viewW` x `viewH` window: as large as fits, never smaller than `minZoom` (so text
 * stays readable; a tall map then shows its top) nor larger than `maxZoom`. Centred sideways when it fits.
 */
export function viewportFor(
  rect: Rect,
  viewW: number,
  viewH: number,
  minZoom = 0.35,
  maxZoom = 1,
  margin = 16,
) {
  const fit = Math.min((viewW - margin * 2) / rect.width, (viewH - margin * 2) / rect.height)
  const zoom = Math.max(minZoom, Math.min(maxZoom, fit))
  const spareX = viewW - rect.width * zoom
  const x = spareX >= margin * 2 ? spareX / 2 - rect.x * zoom : margin - rect.x * zoom
  const spareY = viewH - rect.height * zoom
  const y = spareY >= margin * 2 ? spareY / 2 - rect.y * zoom : margin - rect.y * zoom
  return { x, y, zoom }
}
