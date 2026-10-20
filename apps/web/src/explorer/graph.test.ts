import { describe, expect, it } from 'vitest'
import type { RepoEdge, RepoFile } from '../api/client'
import {
  allDirs,
  ancestorDirs,
  buildGraph,
  defaultExpanded,
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

const dep = (
  src: string,
  dst: string | null,
  confidence = 'resolved',
  extra: Partial<RepoEdge> = {},
): RepoEdge => ({
  src,
  dst,
  kind: 'import',
  confidence,
  line: 1,
  raw: dst ?? 'x',
  provenance: 'python.ast',
  note: null,
  ...extra,
})

describe('dependency edges', () => {
  const open = new Set(['', 'src', 'src/deep'])
  const deps = [
    dep('main.py', 'utils.py'),
    dep('main.py', 'src/app.py'),
    dep('src/app.py', 'src/deep/x.js'),
    dep('utils.py', 'src/app.py', 'heuristic', { kind: 'tests' }),
    dep('main.py', null, 'external'),
  ]

  it('draws only file-to-file relations, each between the real files', () => {
    const g = buildGraph(files, 'r', opts({ expanded: open, dependencies: deps }))
    const d = g.edges.filter((e) => e.data!.kind === 'dependency')
    expect(d.map((e) => `${e.source}>${e.target}`).sort()).toEqual(
      [
        `${fileId('main.py')}>${fileId('utils.py')}`,
        `${fileId('main.py')}>${fileId('src/app.py')}`,
        `${fileId('src/app.py')}>${fileId('src/deep/x.js')}`,
        `${fileId('utils.py')}>${fileId('src/app.py')}`,
      ].sort(),
    )
    expect(d.every((e) => !e.data!.aggregated)).toBe(true)
    expect(g.dependencyEdges).toBe(4)
  })

  it('keeps the confidence of the evidence', () => {
    const g = buildGraph(files, 'r', opts({ expanded: open, dependencies: deps }))
    const e = g.edges.find((x) => x.id === `x:${fileId('utils.py')}>${fileId('src/app.py')}`)!
    expect(e.data!.confidence).toBe('heuristic')
    const r = g.edges.find((x) => x.id === `x:${fileId('main.py')}>${fileId('utils.py')}`)!
    expect(r.data!.confidence).toBe('resolved')
    expect(r.data!.relations[0]!.provenance).toBe('python.ast')
  })

  it('attaches edges to a collapsed folder and says so, counting what it stands for', () => {
    const g = buildGraph(
      files,
      'r',
      opts({
        expanded: new Set(['']),
        dependencies: [dep('main.py', 'src/app.py'), dep('main.py', 'src/deep/x.js')],
      }),
    )
    const e = g.edges.find((x) => x.data!.kind === 'dependency')!
    expect(e.target).toBe(dirId('src'))
    expect(e.data!.aggregated).toBe(true)
    expect(e.data!.count).toBe(2)
  })

  it('drops relations inside one collapsed folder and ones hidden by a filter', () => {
    const inside = buildGraph(files, 'r', opts({ dependencies: [dep('src/app.py', 'src/deep/x.js')] }))
    expect(inside.dependencyEdges).toBe(0)
    const filtered = buildGraph(
      files,
      'r',
      opts({ languages: new Set(['python']), dependencies: [dep('main.py', 'docs/readme.md')] }),
    )
    expect(filtered.dependencyEdges).toBe(0)
  })

  it('never draws a dependency to a file that does not exist in the graph', () => {
    const g = buildGraph(files, 'r', opts({ expanded: open, dependencies: [dep('main.py', 'ghost.py')] }))
    expect(g.dependencyEdges).toBe(0)
  })

  it('caps drawn dependency edges and reports the rest', () => {
    const many = Array.from({ length: 20 }, (_, i) => f(`pkg/f${i}.py`, 'python'))
    const rels = many.slice(1).map((m) => dep(many[0]!.path, m.path))
    const g = buildGraph(
      many,
      'r',
      opts({ expanded: new Set(['', 'pkg']), dependencies: rels, dependencyCap: 5 }),
    )
    expect(g.dependencyEdges).toBe(5)
    expect(g.hiddenDependencyEdges).toBe(14)
  })

  it('flags problems on files and rolls them up to folders', () => {
    const diags = [
      {
        path: 'src/app.py',
        line: 3,
        column: 0,
        severity: 'error',
        code: 'syntax_error',
        message: 'x',
        source: 's',
      },
      {
        path: 'src/deep/x.js',
        line: 1,
        column: 0,
        severity: 'warning',
        code: 'syntax_error',
        message: 'y',
        source: 's',
      },
    ]
    const g = buildGraph(files, 'r', opts({ expanded: new Set(['', 'src']), diagnostics: diags }))
    expect(g.nodes.find((n) => n.id === fileId('src/app.py'))!.data.problems).toBe(1)
    expect(g.nodes.find((n) => n.id === dirId('src'))!.data.problems).toBe(2)
    expect(g.nodes.find((n) => n.id === dirId(''))!.data.problems).toBe(2)
    expect(g.nodes.find((n) => n.id === fileId('main.py'))!.data.problems).toBe(0)
  })

  it('layout ignores dependency edges so the tree stays stable', () => {
    const plain = layoutGraph(
      ...(Object.values(buildGraph(files, 'r', opts({ expanded: open }))).slice(0, 2) as [never, never]),
    )
    const withDeps = buildGraph(files, 'r', opts({ expanded: open, dependencies: deps }))
    const laid = layoutGraph(withDeps.nodes, withDeps.edges)
    expect(laid.map((n) => [n.id, n.position])).toEqual(plain.map((n) => [n.id, n.position]))
  })
})

describe('defaultExpanded', () => {
  it('opens every folder of a small repository so all files are nodes', () => {
    const open = defaultExpanded(files)
    expect(open).toEqual(new Set(['', 'src', 'src/deep', 'docs']))
    const g = buildGraph(files, 'r', { expanded: open, languages: new Set() })
    expect(g.nodes.filter((n) => n.type === 'file').length).toBe(files.length)
    expect(g.truncated).toBe(false)
  })

  it('stops opening folders before the node cap, keeping the result drawable', () => {
    const big = Array.from({ length: 400 }, (_, i) => f(`a/f${i}.py`, 'python'))
    const small = [f('b/x.py'), f('b/y.py')]
    const open = defaultExpanded([...big, ...small], 50)
    expect(open.has('a')).toBe(false) // 400 files would blow the cap
    expect(open.has('b')).toBe(true) // the small folder still opens
    const g = buildGraph([...big, ...small], 'r', { expanded: open, languages: new Set(), cap: 50 })
    expect(g.truncated).toBe(false)
  })

  it('allDirs lists every folder', () => {
    expect(allDirs(files)).toEqual(new Set(['', 'src', 'src/deep', 'docs']))
  })
})
