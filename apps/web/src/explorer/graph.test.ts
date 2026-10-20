import { describe, expect, it } from 'vitest'
import type { RepoFile } from '../api/client'
import {
  ancestorDirs,
  buildGraph,
  dirId,
  fileId,
  languageCounts,
  layoutGraph,
  type GraphOptions,
} from './graph'

const f = (path: string, language = 'plaintext', extra: Partial<RepoFile> = {}): RepoFile => ({
  path,
  language,
  size: 10,
  lines: 2,
  binary: false,
  stored: true,
  skip_reason: null,
  analysis_status: 'not_analyzed',
  ...extra,
})

const files = [
  f('main.py', 'python'),
  f('utils.py', 'python'),
  f('src/app.py', 'python'),
  f('src/deep/x.js', 'javascript'),
  f('docs/readme.md', 'markdown'),
  f('logo.png', 'plaintext', { binary: true, stored: false, skip_reason: 'binary' }),
]
const opts = (over: Partial<GraphOptions> = {}): GraphOptions => ({
  expanded: new Set(['']),
  languages: new Set(),
  ...over,
})

describe('buildGraph', () => {
  it('shows the root and its direct children when only the root is open', () => {
    const g = buildGraph(files, 'octo/hello', opts())
    expect(g.nodes.map((n) => n.id).sort()).toEqual(
      [
        dirId(''),
        dirId('docs'),
        dirId('src'),
        fileId('logo.png'),
        fileId('main.py'),
        fileId('utils.py'),
      ].sort(),
    )
    expect(g.truncated).toBe(false)
  })

  it('keeps files without dependencies and marks unreadable ones', () => {
    const g = buildGraph(files, 'r', opts())
    const logo = g.nodes.find((n) => n.id === fileId('logo.png'))!
    expect(logo.data.note).toBe('binary')
    expect(g.nodes.find((n) => n.id === fileId('main.py'))!.data.note).toBeNull()
  })

  it('every edge is a folder-contains-item fact between two real nodes', () => {
    const g = buildGraph(files, 'r', opts({ expanded: new Set(['', 'src', 'src/deep']) }))
    const ids = new Set(g.nodes.map((n) => n.id))
    expect(g.edges.length).toBe(g.nodes.length - 1) // a tree
    for (const e of g.edges) {
      expect(e.data!.kind).toBe('contains')
      expect(ids.has(e.source) && ids.has(e.target)).toBe(true)
    }
    const e = g.edges.find((x) => x.target === fileId('src/deep/x.js'))!
    expect(e.source).toBe(dirId('src/deep'))
  })

  it('expands only what is asked for', () => {
    const g = buildGraph(files, 'r', opts({ expanded: new Set(['', 'src']) }))
    expect(g.nodes.some((n) => n.id === fileId('src/app.py'))).toBe(true)
    expect(g.nodes.some((n) => n.id === fileId('src/deep/x.js'))).toBe(false)
    expect(g.nodes.find((n) => n.id === dirId('src'))!.data.count).toBe(2)
  })

  it('filters by language and drops folders left empty', () => {
    const g = buildGraph(files, 'r', opts({ languages: new Set(['python']) }))
    expect(g.nodes.some((n) => n.id === dirId('docs'))).toBe(false)
    expect(g.nodes.some((n) => n.id === fileId('logo.png'))).toBe(false)
    expect(g.matchingFiles).toBe(3)
  })

  it('caps the number of nodes and says how much is hidden', () => {
    const many = Array.from({ length: 50 }, (_, i) => f(`pkg/f${i}.py`, 'python'))
    const g = buildGraph(many, 'r', opts({ expanded: new Set(['', 'pkg']), cap: 10 }))
    expect(g.nodes.length).toBe(10)
    expect(g.truncated).toBe(true)
    expect(g.hiddenNodes).toBe(42)
  })
})

describe('layoutGraph', () => {
  it('places children to the right of their parent without overlapping siblings', () => {
    const g = buildGraph(files, 'r', opts())
    const laid = layoutGraph(g.nodes, g.edges)
    const byId = new Map(laid.map((n) => [n.id, n]))
    const root = byId.get(dirId(''))!
    for (const e of g.edges) expect(byId.get(e.target)!.position.x).toBeGreaterThan(root.position.x)
    const ys = laid.filter((n) => n.id !== dirId('')).map((n) => n.position.y)
    expect(new Set(ys).size).toBe(ys.length)
  })
})

it('ancestorDirs lists the root and every parent folder', () => {
  expect(ancestorDirs('a/b/c.py')).toEqual(['', 'a', 'a/b'])
  expect(ancestorDirs('top.py')).toEqual([''])
})

it('languageCounts orders by frequency', () => {
  expect(languageCounts(files)[0]).toEqual(['python', 3])
})
