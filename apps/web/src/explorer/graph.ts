import dagre from '@dagrejs/dagre'
import type { Edge, Node } from '@xyflow/react'
import type { RepoFile } from '../api/client'
import { buildTree, type TreeDir } from './tree'

export const FILE_W = 210
export const FILE_H = 58
export const DIR_W = 210
export const DIR_H = 46
export const DEFAULT_CAP = 300

export type NodeKind = 'file' | 'dir'
export interface GraphNodeData extends Record<string, unknown> {
  kind: NodeKind
  name: string
  path: string
  dir: string // parent folder, for display
  count: number // files under a folder (after filtering)
  expanded: boolean
  language: string
  lines: number
  size: number
  note: string | null // why a file has no readable source
}
export type ExplorerNode = Node<GraphNodeData, NodeKind>

/** What an edge means. Only `contains` exists until dependency analysis lands. */
export type EdgeKind = 'contains'
export interface ExplorerEdgeData extends Record<string, unknown> {
  kind: EdgeKind
  from: string
  to: string
}
export type ExplorerEdge = Edge<ExplorerEdgeData, EdgeKind>

export interface GraphOptions {
  expanded: ReadonlySet<string> // folder paths; '' is the repository root
  languages: ReadonlySet<string> // empty = every language
  cap?: number
}

export interface BuiltGraph {
  nodes: ExplorerNode[]
  edges: ExplorerEdge[]
  truncated: boolean
  hiddenNodes: number
  matchingFiles: number
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

/**
 * The visible part of the repository as a graph. Every edge is a folder-contains-item fact;
 * nothing is inferred. Expansion is on demand and the number of nodes is capped so a huge
 * repository never renders thousands of boxes at once.
 */
export function buildGraph(files: RepoFile[], repoName: string, opts: GraphOptions): BuiltGraph {
  const cap = opts.cap ?? DEFAULT_CAP
  const keep = (f: RepoFile) => opts.languages.size === 0 || opts.languages.has(f.language)
  const root = buildTree(files.filter(keep))
  const nodes: ExplorerNode[] = []
  const edges: ExplorerEdge[] = []
  let hidden = 0

  const add = (n: ExplorerNode, parent: string | null): boolean => {
    if (nodes.length >= cap) {
      hidden++
      return false
    }
    nodes.push(n)
    if (parent !== null) {
      edges.push({
        id: `e:${parent}>${n.id}`,
        source: parent,
        target: n.id,
        type: 'contains',
        data: { kind: 'contains', from: parent, to: n.id },
        focusable: true,
      })
    }
    return true
  }

  const dirNode = (d: TreeDir, name: string): ExplorerNode => ({
    id: dirId(d.path),
    type: 'dir',
    position: { x: 0, y: 0 },
    draggable: true,
    data: {
      kind: 'dir',
      name,
      path: d.path,
      dir: d.path.includes('/') ? d.path.slice(0, d.path.lastIndexOf('/')) : '',
      count: d.fileCount,
      expanded: opts.expanded.has(d.path),
      language: '',
      lines: 0,
      size: 0,
      note: null,
    },
  })

  const visit = (d: TreeDir) => {
    if (!opts.expanded.has(d.path)) return
    const parent = dirId(d.path)
    const queue: TreeDir[] = []
    for (const c of d.children) {
      if (c.kind === 'dir') {
        if (add(dirNode(c, c.name), parent)) queue.push(c)
        else hidden += c.fileCount - 1 // its files are hidden too; the folder itself counted above
      } else {
        add(
          {
            id: fileId(c.path),
            type: 'file',
            position: { x: 0, y: 0 },
            draggable: true,
            data: {
              kind: 'file',
              name: c.name,
              path: c.path,
              dir: d.path,
              count: 0,
              expanded: false,
              language: c.file.language,
              lines: c.file.lines,
              size: c.file.size,
              note: noteFor(c.file),
            },
          },
          parent,
        )
      }
    }
    for (const q of queue) visit(q)
  }

  add(dirNode(root, repoName), null)
  visit(root)
  return {
    nodes,
    edges,
    truncated: hidden > 0,
    hiddenNodes: hidden,
    matchingFiles: root.fileCount,
  }
}

/** Left-to-right tree layout. Returns new nodes with positions; edges are unchanged. */
export function layoutGraph(nodes: ExplorerNode[], edges: ExplorerEdge[]): ExplorerNode[] {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', nodesep: 14, ranksep: 70, marginx: 20, marginy: 20 })
  g.setDefaultEdgeLabel(() => ({}))
  for (const n of nodes) {
    g.setNode(n.id, n.type === 'file' ? { width: FILE_W, height: FILE_H } : { width: DIR_W, height: DIR_H })
  }
  for (const e of edges) g.setEdge(e.source, e.target)
  dagre.layout(g)
  return nodes.map((n) => {
    const p = g.node(n.id)
    const w = n.type === 'file' ? FILE_W : DIR_W
    const h = n.type === 'file' ? FILE_H : DIR_H
    return { ...n, position: { x: p.x - w / 2, y: p.y - h / 2 } }
  })
}

/** Languages present, most common first, for the filter chips. */
export function languageCounts(files: RepoFile[]): [string, number][] {
  const m = new Map<string, number>()
  for (const f of files) m.set(f.language, (m.get(f.language) ?? 0) + 1)
  return [...m.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
}
