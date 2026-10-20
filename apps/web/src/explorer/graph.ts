import type { Edge, Node } from '@xyflow/react'
import type { RepoDiagnostic, RepoEdge, RepoFile } from '../api/client'
import { buildTree, type TreeDir } from './tree'

// ---- layout constants (px). The map is a network: round nodes joined by lines, laid out in rings around the root.
export const FILE_W = 28 // typical node diameter, for older imports
const GAP = 14 // clear space between neighbours
const LEAF_R = 46 // room a file or closed folder takes up, label included

export const DEFAULT_CAP = 300
/** Nodes drawn when a repository first opens: enough to orient yourself, few enough to read. */
export const INITIAL_CAP = 45
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
 * The repository is a network: every folder is a hub, every file a node, and a thin line joins each to its folder.
 * A collapsed folder is a hub you can open. Dependencies are the coloured curves on top.
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
  size: { width: number; height: number } // of the whole network
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
  name: string
  open: boolean
  kids: Item[]
}
type Item = { kind: 'hub'; hub: Hub } | { kind: 'folder'; dir: TreeDir } | { kind: 'file'; file: RepoFile }

const leaves = (it: Item): number =>
  it.kind === 'hub'
    ? Math.max(
        1,
        it.hub.kids.reduce((n, k) => n + leaves(k), 0),
      )
    : 1

/** Node diameters: files grow slowly with their length, hubs with the number of files they hold. */
const fileDiameter = (lines: number) => Math.round(Math.min(46, 22 + 4.5 * Math.log2(lines + 1)))
const hubDiameter = (count: number, root: boolean) =>
  root ? 76 : Math.round(Math.min(64, 40 + 4 * Math.log2(count + 1)))

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
  const makeHub = (dir: TreeDir, name: string): Hub => {
    used++ // the hub itself
    const hub: Hub = { dir, name, open: true, kids: [] }
    for (const c of dir.children) {
      if (c.kind === 'dir') {
        if (opts.expanded.has(c.path) && used < cap) hub.kids.push({ kind: 'hub', hub: makeHub(c, c.name) })
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
  const rootHub = makeHub(root, repoName)

  // 2. layout: each open folder is a hub with its contents on rings around it. A folder's whole cluster is measured
  // first (its radius), so neighbouring clusters never overlap. Ring after ring, nothing is stretched into a long line.
  const ids = new Map<Item, string>()
  const idOf = (it: Item): string => {
    let id = ids.get(it)
    if (!id) {
      id =
        it.kind === 'hub'
          ? dirId(it.hub.dir.path)
          : it.kind === 'folder'
            ? dirId(it.dir.path)
            : fileId(it.file.path)
      ids.set(it, id)
    }
    return id
  }
  const hubR = (hub: Hub) => hubDiameter(hub.dir.fileCount, hub.dir.path === '') / 2
  const clusterR = new Map<Hub, number>()
  const ringsOf = new Map<Hub, { r: number; items: Item[] }[]>()
  const radiusOf = (it: Item): number => (it.kind === 'hub' ? measure(it.hub) : LEAF_R)
  const measure = (hub: Hub): number => {
    const kids = [...hub.kids].sort((a, b) => radiusOf(b) - radiusOf(a))
    const rings: { r: number; items: Item[]; max: number }[] = []
    let ring: { r: number; items: Item[]; max: number } | null = null
    let used = 0
    for (const k of kids) {
      const rk = radiusOf(k)
      const arc = 2 * rk + GAP
      if (ring && used + arc <= Math.PI * 2 * ring.r * 0.96) {
        ring.items.push(k)
        used += arc
        ring.max = Math.max(ring.max, rk)
        continue
      }
      const r: number = ring ? ring.r + ring.max + rk + GAP : hubR(hub) + rk + GAP + 18
      ring = { r, items: [k], max: rk }
      rings.push(ring)
      used = arc
    }
    ringsOf.set(hub, rings)
    const total = rings.length ? rings[rings.length - 1]!.r + rings[rings.length - 1]!.max : hubR(hub)
    clusterR.set(hub, total)
    return total
  }
  measure(rootHub)
  const placed: { id: string; item: Item; parent: string | null; cx: number; cy: number }[] = []
  const lay = (it: Item, cx: number, cy: number, parent: string | null) => {
    placed.push({ id: idOf(it), item: it, parent, cx, cy })
    if (it.kind !== 'hub') return
    ringsOf.get(it.hub)!.forEach((ring, ri) => {
      const total = ring.items.reduce((n, k) => n + 2 * radiusOf(k) + GAP, 0)
      let a = ri % 2 === 0 ? -Math.PI / 2 : -Math.PI / 2 + Math.PI / ring.items.length
      for (const k of ring.items) {
        const width = ((2 * radiusOf(k) + GAP) / total) * Math.PI * 2
        const mid = a + width / 2
        lay(k, cx + Math.cos(mid) * ring.r, cy + Math.sin(mid) * ring.r, idOf(it))
        a += width
      }
    })
  }
  lay({ kind: 'hub', hub: rootHub }, 0, 0, null)
  const at = new Map(placed.map((p) => [p.id, { cx: p.cx, cy: p.cy }]))

  // 3. nodes and the thin lines that join each to its folder
  const nodes: ExplorerNode[] = []
  const edges: ExplorerEdge[] = []
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity // prettier-ignore
  for (const p of placed) {
    const pos = at.get(p.id)!
    const it = p.item
    let data: GraphNodeData
    let type: NodeKind
    if (it.kind === 'file') {
      const f = it.file
      const d = fileDiameter(f.lines)
      type = 'file'
      data = {
        kind: 'file', name: f.path.slice(f.path.lastIndexOf('/') + 1), path: f.path, count: 0, expanded: false,
        language: f.language, lines: f.lines, size: f.size, note: noteFor(f), problems: problemsByPath.get(f.path) ?? 0,
        width: d, height: d,
      } // prettier-ignore
    } else {
      const dir = it.kind === 'hub' ? it.hub.dir : it.dir
      const isRoot = dir.path === ''
      const d = hubDiameter(dir.fileCount, isRoot)
      type = 'folder'
      data = {
        kind: 'folder', name: isRoot ? repoName : dir.name, path: dir.path, count: dir.fileCount,
        expanded: it.kind === 'hub', language: '', lines: 0, size: 0, note: null, problems: problemsUnder(dir.path),
        width: d, height: d,
      } // prettier-ignore
    }
    const w = data.width
    nodes.push({
      id: p.id, type, position: { x: pos.cx - w / 2, y: pos.cy - w / 2 }, draggable: false, selectable: false,
      width: w, height: w, style: { width: w, height: w }, data,
    }) // prettier-ignore
    minX = Math.min(minX, pos.cx - w / 2 - 50)
    maxX = Math.max(maxX, pos.cx + w / 2 + 50)
    minY = Math.min(minY, pos.cy - w / 2 - 20)
    maxY = Math.max(maxY, pos.cy + w / 2 + 40)
    if (p.parent) {
      edges.push({
        id: `t:${p.parent}>${p.id}`, source: p.parent, target: p.id, type: 'tree',
        selectable: false, focusable: false,
        data: { kind: 'tree', from: p.parent, to: p.id, relations: [], count: 0, aggregated: false, confidence: 'resolved', direction: '' },
      }) // prettier-ignore
    }
  }

  // 4. dependency lines, only as many as can be read
  const dep = buildDependencyEdges(nodes, opts)
  return {
    nodes,
    edges: [...edges, ...dep.edges],
    truncated: hidden > 0,
    hiddenNodes: hidden,
    matchingFiles: root.fileCount,
    dependencyEdges: dep.edges.length,
    hiddenDependencyEdges: dep.hidden,
    size: { width: maxX - minX, height: maxY - minY },
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

/** Where a node is, including the label that hangs under it. */
export function absoluteRect(nodes: ExplorerNode[], id: string): Rect | null {
  const n = nodes.find((x) => x.id === id)
  if (!n) return null
  return { x: n.position.x, y: n.position.y, width: n.data.width, height: n.data.height }
}

/** The box around every node, with room for labels: what "fit the whole network" frames. */
export function boundsOf(nodes: ExplorerNode[]): Rect | null {
  if (nodes.length === 0) return null
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity // prettier-ignore
  for (const n of nodes) {
    x0 = Math.min(x0, n.position.x - 40)
    y0 = Math.min(y0, n.position.y - 10)
    x1 = Math.max(x1, n.position.x + n.data.width + 40)
    y1 = Math.max(y1, n.position.y + n.data.height + 36)
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
