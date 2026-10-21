import type { Edge, Node } from '@xyflow/react'
import type { RepoDiagnostic, RepoEdge, RepoFile } from '../api/client'
import { buildTree, type TreeDir } from './tree'

// ---- layout constants (px). The repository is a tree read left to right: a folder, then what it holds.
export const NODE_W = 210
export const NODE_H = 46
export const FILE_W = NODE_W // kept for older imports
const COL_GAP = 90 // between a folder and what it holds
const ROW_GAP = 12 // between neighbouring nodes in a column

export const DEFAULT_CAP = 300
/** Nodes drawn when a repository first opens: enough to orient yourself, few enough to read. */
export const INITIAL_CAP = 60
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
 * The repository is a tree read left to right: every folder and file is a node, joined to its folder by a curve.
 * A collapsed folder is a node you can open. Dependencies are the coloured curves on top.
 */
export type NodeKind = 'file' | 'folder'
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
export type EdgeKind = 'dependency' | 'tree'
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
  size: { width: number; height: number } // of the whole tree
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

interface Hub {
  dir: TreeDir
  kids: Item[]
}
type Item = { kind: 'hub'; hub: Hub } | { kind: 'folder'; dir: TreeDir } | { kind: 'file'; file: RepoFile }

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

  // 1. which folders open, within the node budget
  let used = 0
  let hidden = 0
  const makeHub = (dir: TreeDir): Hub => {
    used++ // the folder itself
    const hub: Hub = { dir, kids: [] }
    for (const c of dir.children) {
      if (c.kind === 'dir') {
        if (opts.expanded.has(c.path) && used < cap) hub.kids.push({ kind: 'hub', hub: makeHub(c) })
        else if (used < cap) {
          used++
          hub.kids.push({ kind: 'folder', dir: c })
        } else hidden += 1 + c.fileCount
      } else if (used < cap) {
        used++
        hub.kids.push({ kind: 'file', file: (c as { file: RepoFile }).file })
      } else hidden++
    }
    return hub
  }
  const rootHub = makeHub(root)

  // 2. tidy tree: one column per depth, leaves in consecutive rows, a folder centred beside what it holds
  const rowH = NODE_H + ROW_GAP
  let nextRow = 0
  const nodes: ExplorerNode[] = []
  const edges: ExplorerEdge[] = []
  const place = (it: Item, depth: number, parent: string | null): { id: string; y: number } => {
    const id =
      it.kind === 'file' ? fileId(it.file.path) : dirId(it.kind === 'hub' ? it.hub.dir.path : it.dir.path)
    let y: number
    const index = nodes.length
    nodes.push(null as unknown as ExplorerNode) // keeps parents before children
    if (it.kind === 'hub' && it.hub.kids.length > 0) {
      const ys = it.hub.kids.map((k) => place(k, depth + 1, id).y)
      y = (ys[0]! + ys[ys.length - 1]!) / 2
    } else {
      y = nextRow++ * rowH
    }
    let data: GraphNodeData
    let type: NodeKind
    if (it.kind === 'file') {
      const f = it.file
      type = 'file'
      data = {
        kind: 'file', name: f.path.slice(f.path.lastIndexOf('/') + 1), path: f.path, count: 0, expanded: false,
        language: f.language, lines: f.lines, size: f.size, note: noteFor(f), problems: problemsByPath.get(f.path) ?? 0,
        width: NODE_W, height: NODE_H,
      } // prettier-ignore
    } else {
      const dir = it.kind === 'hub' ? it.hub.dir : it.dir
      type = 'folder'
      data = {
        kind: 'folder', name: dir.path === '' ? repoName : dir.name, path: dir.path, count: dir.fileCount,
        expanded: it.kind === 'hub', language: '', lines: 0, size: 0, note: null, problems: problemsUnder(dir.path),
        width: NODE_W, height: NODE_H,
      } // prettier-ignore
    }
    nodes[index] = {
      id, type, position: { x: depth * (NODE_W + COL_GAP), y }, draggable: false, selectable: false,
      width: NODE_W, height: NODE_H, style: { width: NODE_W, height: NODE_H }, data,
    } // prettier-ignore
    if (parent) {
      edges.push({
        id: `t:${parent}>${id}`, source: parent, target: id, type: 'tree', selectable: false, focusable: false,
        data: { kind: 'tree', from: parent, to: id, relations: [], count: 0, aggregated: false, confidence: 'resolved', direction: '' },
      }) // prettier-ignore
    }
    return { id, y }
  }
  place({ kind: 'hub', hub: rootHub }, 0, null)
  const maxX = nodes.reduce((m, n) => Math.max(m, n.position.x + NODE_W), 0)
  const maxY = nodes.reduce((m, n) => Math.max(m, n.position.y + NODE_H), 0)

  // 3. dependency lines, only as many as can be read
  const dep = buildDependencyEdges(nodes, opts)
  return {
    nodes,
    edges: [...edges, ...dep.edges],
    truncated: hidden > 0,
    hiddenNodes: hidden,
    matchingFiles: root.fileCount,
    dependencyEdges: dep.edges.length,
    hiddenDependencyEdges: dep.hidden,
    size: { width: maxX, height: maxY },
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
    if (n) return n.data.expanded ? null : id
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

/** Where a node is. */
export function absoluteRect(nodes: ExplorerNode[], id: string): Rect | null {
  const n = nodes.find((x) => x.id === id)
  if (!n) return null
  return { x: n.position.x, y: n.position.y, width: n.data.width, height: n.data.height }
}

/** The box around every node, what "fit the whole network" frames. */
export function boundsOf(nodes: ExplorerNode[]): Rect | null {
  if (nodes.length === 0) return null
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity // prettier-ignore
  for (const n of nodes) {
    x0 = Math.min(x0, n.position.x - 20)
    y0 = Math.min(y0, n.position.y - 20)
    x1 = Math.max(x1, n.position.x + n.data.width + 20)
    y1 = Math.max(y1, n.position.y + n.data.height + 20)
  }
  return { x: x0, y: y0, width: x1 - x0, height: y1 - y0 }
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
