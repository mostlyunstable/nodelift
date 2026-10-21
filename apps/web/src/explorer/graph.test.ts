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

const isDep = (e: { type?: string }) => e.type === 'dependency'
const overlap = (a: ExplorerNode, b: ExplorerNode) =>
  a.position.x < b.position.x + b.data.width &&
  b.position.x < a.position.x + a.data.width &&
  a.position.y < b.position.y + b.data.height &&
  b.position.y < a.position.y + a.data.height

describe('the repository is a tree read left to right', () => {
  it('the root starts it; its folders are closed boxes you can open, its files are boxes', () => {
    const g = buildGraph(files, 'octo/hello', opts())
    const byId = new Map(g.nodes.map((n) => [n.id, n]))
    expect(byId.get(dirId(''))!.type).toBe('folder')
    expect(byId.get(dirId(''))!.data.expanded).toBe(true)
    expect(byId.get(dirId(''))!.position.x).toBe(0)
    expect(byId.get(dirId('src'))!.data.expanded).toBe(false)
    expect(byId.get(fileId('main.py'))!.type).toBe('file')
    expect(g.edges.every((e) => e.type === 'tree' && e.source === dirId(''))).toBe(true)
    expect(g.edges).toHaveLength(g.nodes.length - 1)
  })

  it('what a folder holds sits one column to its right, joined by a line', () => {
    const g = buildGraph(files, 'r', opts({ expanded: new Set(['', 'src', 'src/deep']) }))
    const by = new Map(g.nodes.map((n) => [n.id, n]))
    expect(by.get(dirId('src'))!.data.expanded).toBe(true)
    expect(by.get(dirId('src'))!.data.count).toBe(2)
    const x = (id: string) => by.get(id)!.position.x
    expect(x(dirId('src/deep'))).toBeGreaterThan(x(dirId('src')))
    expect(x(fileId('src/deep/x.js'))).toBeGreaterThan(x(dirId('src/deep')))
    const lines = g.edges.map((e) => `${e.source}>${e.target}`)
    expect(lines).toContain(`${dirId('src')}>${dirId('src/deep')}`)
    expect(lines).toContain(`${dirId('src/deep')}>${fileId('src/deep/x.js')}`)
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

describe('the layout is a landscape, tidy and compact', () => {
  const synthetic = {
    'one flat folder of 120 files': Array.from({ length: 120 }, (_, i) => f(`a${i}.py`, 'python')),
    'eight folders of 15': Array.from({ length: 120 }, (_, i) => f(`pkg${i % 8}/m${i}.py`, 'python')),
    'a three-level tree': Array.from({ length: 90 }, (_, i) =>
      f(`a${i % 3}/b${i % 5}/c${i % 2}/f${i}.py`, 'python'),
    ),
    'mixed tree': [
      ...Array.from({ length: 30 }, (_, i) => f(`src/core/c${i}.py`, 'python')),
      ...Array.from({ length: 12 }, (_, i) => f(`src/util/u${i}.py`, 'python')),
      ...Array.from({ length: 25 }, (_, i) => f(`tests/t${i}.py`, 'python')),
      ...Array.from({ length: 8 }, (_, i) => f(`docs/d${i}.md`, 'markdown')),
      f('README.md', 'markdown'),
    ],
  }
  for (const [name, repo] of Object.entries(synthetic)) {
    it(`${name}: no two nodes overlap and a folder sits level with what it holds`, () => {
      const g = buildGraph(repo, 'r', opts({ expanded: allDirs(repo), cap: 500 }))
      for (let i = 0; i < g.nodes.length; i++)
        for (let j = i + 1; j < g.nodes.length; j++)
          expect(overlap(g.nodes[i]!, g.nodes[j]!), `${g.nodes[i]!.id} / ${g.nodes[j]!.id}`).toBe(false)
      const { width, height } = g.size
      expect(width / height, `${width}x${height}`).toBeGreaterThan(1)
      expect(width / height).toBeLessThan(4)
    })
  }

  it('a folder of 60 files is a grid, wider than tall, not 60 stacked rows', () => {
    const repo = Array.from({ length: 60 }, (_, i) => f(`pkg/m${i}.py`, 'python'))
    const g = buildGraph(repo, 'r', opts({ expanded: new Set(['', 'pkg']), cap: 500 }))
    const xs = new Set(g.nodes.filter((n) => n.type === 'file').map((n) => n.position.x))
    expect(xs.size).toBeGreaterThanOrEqual(4)
    expect(g.size.width).toBeGreaterThan(g.size.height)
  })

  it('every node sits right of the folder that holds it', () => {
    const repo = Array.from({ length: 30 }, (_, i) => f(`a/b/f${i}.py`, 'python'))
    const g = buildGraph(repo, 'r', opts({ expanded: allDirs(repo), cap: 500 }))
    const by = new Map(g.nodes.map((n) => [n.id, n]))
    for (const e of g.edges.filter((x) => x.type === 'tree'))
      expect(by.get(e.target)!.position.x).toBeGreaterThan(by.get(e.source)!.position.x)
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
    const lines = g.edges
      .filter(isDep)
      .map((e) => `${e.source}>${e.target}:${e.data!.direction}`)
      .sort()
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
      buildGraph(files, 'r', opts({ expanded: open, dependencies: deps, depMode: 'selected' })).edges.filter(
        isDep,
      ),
    ).toEqual([])
    expect(
      buildGraph(
        files,
        'r',
        opts({ expanded: open, dependencies: deps, depMode: 'off', selectedPath: 'main.py' }),
      ).edges.filter(isDep),
    ).toEqual([])
  })

  it('"all" draws every file-to-file relation once, keeps confidence, and never an external one', () => {
    const g = buildGraph(files, 'r', opts({ expanded: open, dependencies: deps, depMode: 'all' }))
    expect(g.edges.filter(isDep)).toHaveLength(4)
    expect(
      g.edges.filter(isDep).find((e) => e.id === `x:${fileId('utils.py')}>${fileId('src/app.py')}`)!.data!
        .confidence,
    ).toBe('heuristic')
    expect(
      g.edges.filter(isDep).find((e) => e.id === `x:${fileId('main.py')}>${fileId('utils.py')}`)!.data!
        .relations[0]!.provenance,
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
    const toSrc = g.edges.filter(isDep).find((e) => e.target === dirId('src'))!
    expect(toSrc.source).toBe(fileId('main.py'))
    expect(toSrc.data!.count).toBe(2)
    expect(toSrc.data!.aggregated).toBe(true)
    expect(g.edges.filter(isDep)[0]!.data!.count).toBeGreaterThanOrEqual(
      g.edges.filter(isDep)[g.edges.filter(isDep).length - 1]!.data!.count,
    )
  })

  it('attaches a line to the folder tile hiding a file and marks it aggregated', () => {
    const g = buildGraph(
      files,
      'r',
      opts({ expanded: new Set(['']), dependencies: [rel('main.py', 'src/app.py')], depMode: 'all' }),
    )
    expect(g.edges.filter(isDep)[0]!.target).toBe(dirId('src'))
    expect(g.edges.filter(isDep)[0]!.data!.aggregated).toBe(true)
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
