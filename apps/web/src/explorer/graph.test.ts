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
  shouldDefaultToCodeOnly,
  type ExplorerNode,
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

/** Absolute rectangle of every node, walking up through parent cards. */
function rects(nodes: ExplorerNode[]) {
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const out = new Map<string, { x1: number; y1: number; x2: number; y2: number }>()
  const abs = (n: ExplorerNode): { x: number; y: number } => {
    const p = n.parentId ? abs(byId.get(n.parentId)!) : { x: 0, y: 0 }
    return { x: p.x + n.position.x, y: p.y + n.position.y }
  }
  for (const n of nodes) {
    const a = abs(n)
    out.set(n.id, { x1: a.x, y1: a.y, x2: a.x + n.data.width, y2: a.y + n.data.height })
  }
  return out
}
const overlap = (a: { x1: number; y1: number; x2: number; y2: number }, b: typeof a) =>
  a.x1 < b.x2 && b.x1 < a.x2 && a.y1 < b.y2 && b.y1 < a.y2

describe('folders are cards, files are tiles', () => {
  it('the root is a card; its folders start as tiles you can open, its files are tiles', () => {
    const g = buildGraph(files, 'octo/hello', opts())
    const byId = new Map(g.nodes.map((n) => [n.id, n]))
    expect(byId.get(dirId(''))!.type).toBe('card')
    expect(byId.get(dirId('src'))!.type).toBe('folder')
    expect(byId.get(dirId('docs'))!.type).toBe('folder')
    expect(byId.get(fileId('main.py'))!.type).toBe('file')
    expect(g.nodes.every((n) => n.id === dirId('') || n.parentId === dirId(''))).toBe(true)
    expect(g.edges).toEqual([]) // containment is nesting, not lines
  })

  it('an open folder becomes a card nested inside its parent card', () => {
    const g = buildGraph(files, 'r', opts({ expanded: new Set(['', 'src', 'src/deep']) }))
    const byId = new Map(g.nodes.map((n) => [n.id, n]))
    expect(byId.get(dirId('src'))!.type).toBe('card')
    expect(byId.get(dirId('src'))!.parentId).toBe(dirId(''))
    expect(byId.get(dirId('src/deep'))!.parentId).toBe(dirId('src'))
    expect(byId.get(fileId('src/deep/x.js'))!.parentId).toBe(dirId('src/deep'))
    expect(byId.get(dirId('src'))!.data.count).toBe(2)
  })

  it('keeps every file, including ones nothing depends on, and says why one cannot be read', () => {
    const g = buildGraph(files, 'r', opts({ expanded: new Set(['', 'src', 'src/deep', 'docs']) }))
    expect(g.nodes.filter((n) => n.type === 'file')).toHaveLength(files.length)
    expect(g.nodes.find((n) => n.id === fileId('logo.png'))!.data.note).toBe('binary')
    expect(g.truncated).toBe(false)
  })

  it('filters by language and by code-only, dropping folders left empty', () => {
    const py = buildGraph(
      files,
      'r',
      opts({ languages: new Set(['python']), expanded: new Set(['', 'src', 'docs']) }),
    )
    expect(py.nodes.some((n) => n.id === dirId('docs'))).toBe(false)
    expect(py.matchingFiles).toBe(3)
    const code = buildGraph(files, 'r', opts({ codeOnly: true }))
    expect(code.nodes.some((n) => n.id === fileId('logo.png') || n.id === dirId('docs'))).toBe(false)
  })

  it('rolls problems up to folders and ignores notes', () => {
    const d = (path: string, severity: string) => ({
      path,
      line: 1,
      column: 1,
      severity,
      code: 'x',
      message: 'm',
      source: 's',
    })
    const g = buildGraph(
      files,
      'r',
      opts({
        expanded: new Set(['', 'src']),
        diagnostics: [
          d('src/app.py', 'error'),
          d('src/deep/x.js', 'warning'),
          d('src/app.py', 'info'),
          d('main.py', 'info'),
        ],
      }),
    )
    const by = new Map(g.nodes.map((n) => [n.id, n.data.problems]))
    expect(by.get(fileId('src/app.py'))).toBe(1)
    expect(by.get(dirId('src'))).toBe(2)
    expect(by.get(dirId(''))).toBe(2)
    expect(by.get(fileId('main.py'))).toBe(0)
  })

  it('caps the number of items and says how many are hidden', () => {
    const many = Array.from({ length: 50 }, (_, i) => f(`pkg/f${i}.py`, 'python'))
    const g = buildGraph(many, 'r', opts({ expanded: new Set(['', 'pkg']), cap: 10 }))
    expect(g.nodes.length).toBe(10)
    expect(g.truncated).toBe(true)
    expect(g.hiddenNodes).toBe(42)
  })
})

describe('the layout is a tidy map, not a long line', () => {
  const synthetic = {
    'one flat folder of 120 files': Array.from({ length: 120 }, (_, i) => f(`a${i}.py`, 'python')),
    'eight folders of 15': Array.from({ length: 120 }, (_, i) => f(`pkg${i % 8}/m${i}.py`, 'python')),
    'a deep chain': Array.from({ length: 40 }, (_, i) => f(`${'d/'.repeat((i % 8) + 1)}f${i}.py`, 'python')),
    'mixed tree': [
      ...Array.from({ length: 30 }, (_, i) => f(`src/core/c${i}.py`, 'python')),
      ...Array.from({ length: 12 }, (_, i) => f(`src/util/u${i}.py`, 'python')),
      ...Array.from({ length: 25 }, (_, i) => f(`tests/t${i}.py`, 'python')),
      ...Array.from({ length: 8 }, (_, i) => f(`docs/d${i}.md`, 'markdown')),
      f('README.md', 'markdown'),
    ],
  }
  for (const [name, repo] of Object.entries(synthetic)) {
    it(`${name}: nothing overlaps, everything sits inside its card, and the shape is compact`, () => {
      const g = buildGraph(repo, 'r', opts({ expanded: allDirs(repo), cap: 500 }))
      const r = rects(g.nodes)
      const ids = [...r.keys()]
      // siblings never overlap (children of the same card)
      const byParent = new Map<string | undefined, ExplorerNode[]>()
      for (const n of g.nodes) byParent.set(n.parentId, [...(byParent.get(n.parentId) ?? []), n])
      for (const sibs of byParent.values())
        for (let i = 0; i < sibs.length; i++)
          for (let j = i + 1; j < sibs.length; j++)
            expect(overlap(r.get(sibs[i]!.id)!, r.get(sibs[j]!.id)!), `${sibs[i]!.id} / ${sibs[j]!.id}`).toBe(
              false,
            )
      // every child is inside its parent card
      for (const n of g.nodes) {
        if (!n.parentId) continue
        const c = r.get(n.id)!
        const p = r.get(n.parentId)!
        expect(
          c.x1 >= p.x1 && c.y1 >= p.y1 && c.x2 <= p.x2 && c.y2 <= p.y2,
          `${n.id} inside ${n.parentId}`,
        ).toBe(true)
      }
      // not a long line: the whole map is roughly landscape, never a thin strip either way
      const { width, height } = g.size
      expect(width / height, `${width}x${height}`).toBeGreaterThan(0.55)
      expect(width / height).toBeLessThan(3.2)
      expect(ids.length).toBeGreaterThan(0)
    })
  }

  it('a folder of 60 files is a block of columns, not 60 stacked rows', () => {
    const repo = Array.from({ length: 60 }, (_, i) => f(`pkg/m${i}.py`, 'python'))
    const g = buildGraph(repo, 'r', opts({ expanded: new Set(['', 'pkg']), cap: 500 }))
    const pkg = g.nodes.find((n) => n.id === dirId('pkg'))!
    expect(pkg.data.height).toBeLessThan(60 * 56 * 0.3)
    const xs = new Set(g.nodes.filter((n) => n.type === 'file').map((n) => n.position.x))
    expect(xs.size).toBeGreaterThanOrEqual(4)
  })
})

describe('dependency lines are drawn on demand', () => {
  const rel = (
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
  const open = new Set(['', 'src', 'src/deep'])
  const deps = [
    rel('main.py', 'utils.py'),
    rel('main.py', 'src/app.py'),
    rel('src/app.py', 'src/deep/x.js'),
    rel('utils.py', 'src/app.py', 'heuristic', { kind: 'tests' }),
    rel('main.py', null, 'external'),
  ]

  it('"selected" draws only what touches the chosen file, with direction', () => {
    const g = buildGraph(
      files,
      'r',
      opts({ expanded: open, dependencies: deps, depMode: 'selected', selectedPath: 'src/app.py' }),
    )
    const lines = g.edges.map((e) => `${e.source}>${e.target}:${e.data!.direction}`).sort()
    expect(lines).toEqual(
      [
        `${fileId('main.py')}>${fileId('src/app.py')}:in`,
        `${fileId('utils.py')}>${fileId('src/app.py')}:in`,
        `${fileId('src/app.py')}>${fileId('src/deep/x.js')}:out`,
      ].sort(),
    )
  })

  it('"selected" with nothing selected, and "off", draw nothing', () => {
    expect(
      buildGraph(files, 'r', opts({ expanded: open, dependencies: deps, depMode: 'selected' })).edges,
    ).toEqual([])
    expect(
      buildGraph(
        files,
        'r',
        opts({ expanded: open, dependencies: deps, depMode: 'off', selectedPath: 'main.py' }),
      ).edges,
    ).toEqual([])
  })

  it('"all" draws every file-to-file relation once, keeps confidence, and never an external one', () => {
    const g = buildGraph(files, 'r', opts({ expanded: open, dependencies: deps, depMode: 'all' }))
    expect(g.edges).toHaveLength(4)
    expect(
      g.edges.find((e) => e.id === `x:${fileId('utils.py')}>${fileId('src/app.py')}`)!.data!.confidence,
    ).toBe('heuristic')
    expect(
      g.edges.find((e) => e.id === `x:${fileId('main.py')}>${fileId('utils.py')}`)!.data!.relations[0]!
        .provenance,
    ).toBe('python.ast')
  })

  it('"folders" shows the strongest links between top-level items, counted', () => {
    const many = [
      rel('main.py', 'src/app.py'),
      rel('utils.py', 'src/app.py'),
      rel('main.py', 'src/deep/x.js'),
      rel('main.py', 'utils.py'),
    ]
    const g = buildGraph(
      files,
      'r',
      opts({ expanded: new Set(['']), dependencies: many, depMode: 'folders' }),
    )
    const toSrc = g.edges.find((e) => e.target === dirId('src'))!
    expect(toSrc.source).toBe(fileId('main.py'))
    expect(toSrc.data!.count).toBe(2)
    expect(toSrc.data!.aggregated).toBe(true)
    expect(g.edges[0]!.data!.count).toBeGreaterThanOrEqual(g.edges[g.edges.length - 1]!.data!.count)
  })

  it('attaches a line to the folder tile hiding a file and marks it aggregated', () => {
    const g = buildGraph(
      files,
      'r',
      opts({ expanded: new Set(['']), dependencies: [rel('main.py', 'src/app.py')], depMode: 'all' }),
    )
    expect(g.edges[0]!.target).toBe(dirId('src'))
    expect(g.edges[0]!.data!.aggregated).toBe(true)
  })

  it('draws nothing for files that are filtered out or do not exist', () => {
    const filtered = buildGraph(
      files,
      'r',
      opts({
        languages: new Set(['python']),
        dependencies: [rel('main.py', 'docs/readme.md')],
        depMode: 'all',
      }),
    )
    expect(filtered.dependencyEdges).toBe(0)
    expect(
      buildGraph(
        files,
        'r',
        opts({ expanded: open, dependencies: [rel('main.py', 'ghost.py')], depMode: 'all' }),
      ).dependencyEdges,
    ).toBe(0)
  })

  it('caps the lines and reports how many were left out', () => {
    const many = Array.from({ length: 20 }, (_, i) => f(`pkg/f${i}.py`, 'python'))
    const rels = many.slice(1).map((m) => rel(many[0]!.path, m.path))
    const g = buildGraph(
      many,
      'r',
      opts({ expanded: new Set(['', 'pkg']), dependencies: rels, depMode: 'all', dependencyCap: 5 }),
    )
    expect(g.dependencyEdges).toBe(5)
    expect(g.hiddenDependencyEdges).toBe(14)
  })
})

it('ancestorDirs lists the root and every parent folder', () => {
  expect(ancestorDirs('a/b/c.py')).toEqual(['', 'a', 'a/b'])
  expect(ancestorDirs('top.py')).toEqual([''])
})

it('languageCounts orders by frequency', () => {
  expect(languageCounts(files)[0]).toEqual(['python', 3])
})

describe('defaultExpanded', () => {
  it('opens every folder of a small repository so all files are visible', () => {
    const open = defaultExpanded(files)
    expect(open).toEqual(new Set(['', 'src', 'src/deep', 'docs']))
    const g = buildGraph(files, 'r', { expanded: open, languages: new Set() })
    expect(g.nodes.filter((n) => n.type === 'file')).toHaveLength(files.length)
    expect(g.truncated).toBe(false)
  })

  it('opens folders that hold code before documentation folders when the budget is tight', () => {
    const repo = [
      ...Array.from({ length: 30 }, (_, i) => f(`docs/d${i}.md`, 'markdown')),
      ...Array.from({ length: 30 }, (_, i) => f(`src/s${i}.py`, 'python')),
    ]
    const open = defaultExpanded(repo, 40)
    expect(open.has('src')).toBe(true)
    expect(open.has('docs')).toBe(false)
  })

  it('code-only hides docs and config, and big repositories default to it', () => {
    const repo = [
      ...Array.from({ length: 70 }, (_, i) => f(`docs/d${i}.md`, 'markdown')),
      ...Array.from({ length: 6 }, (_, i) => f(`src/s${i}.py`, 'python')),
    ]
    expect(shouldDefaultToCodeOnly(repo)).toBe(true)
    expect(shouldDefaultToCodeOnly(files)).toBe(false)
    const g = buildGraph(repo, 'r', {
      expanded: new Set(['', 'src', 'docs']),
      languages: new Set(),
      codeOnly: true,
    })
    expect(g.nodes.some((n) => n.id === dirId('docs'))).toBe(false)
    expect(g.nodes.filter((n) => n.type === 'file')).toHaveLength(6)
  })

  it('stops opening folders before the budget, keeping the result drawable', () => {
    const big = Array.from({ length: 400 }, (_, i) => f(`a/f${i}.py`, 'python'))
    const small = [f('b/x.py'), f('b/y.py')]
    const open = defaultExpanded([...big, ...small], 50)
    expect(open.has('a')).toBe(false)
    expect(open.has('b')).toBe(true)
    expect(
      buildGraph([...big, ...small], 'r', { expanded: open, languages: new Set(), cap: 50 }).truncated,
    ).toBe(false)
  })

  it('allDirs lists every folder', () => {
    expect(allDirs(files)).toEqual(new Set(['', 'src', 'src/deep', 'docs']))
  })
})
