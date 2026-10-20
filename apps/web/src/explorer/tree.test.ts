import { describe, expect, it } from 'vitest'
import type { RepoFile } from '../api/client'
import { buildTree, formatBytes, searchFiles } from './tree'

const f = (path: string): RepoFile => ({
  path,
  language: 'plaintext',
  size: 1,
  lines: 1,
  binary: false,
  stored: true,
  skip_reason: null,
  analysis_status: 'not_analyzed',
})

describe('buildTree', () => {
  const files = ['b.py', 'src/z.py', 'src/A.py', 'src/deep/x.py', 'README.md'].map(f)
  const root = buildTree(files)

  it('puts folders first and sorts case-insensitively', () => {
    expect(root.children.map((c) => c.name)).toEqual(['src', 'b.py', 'README.md'])
    const src = root.children[0]!
    expect(src.kind === 'dir' && src.children.map((c) => c.name)).toEqual(['deep', 'A.py', 'z.py'])
  })

  it('counts every file under each folder and keeps every file', () => {
    expect(root.fileCount).toBe(5)
    const src = root.children[0]!
    expect(src.kind === 'dir' && src.fileCount).toBe(3)
  })
})

describe('searchFiles', () => {
  const files = ['src/main.py', 'src/Utils.py', 'docs/a.md'].map(f)
  it('matches case-insensitively on the full path', () => {
    expect(searchFiles(files, 'UTIL').map((x) => x.path)).toEqual(['src/Utils.py'])
    expect(searchFiles(files, 'src/').length).toBe(2)
  })
  it('returns nothing for an empty query and respects the limit', () => {
    expect(searchFiles(files, '  ')).toEqual([])
    expect(searchFiles(files, 'a', 1).length).toBe(1)
  })
})

it('formats sizes', () => {
  expect(formatBytes(10)).toBe('10 B')
  expect(formatBytes(2048)).toBe('2.0 KB')
  expect(formatBytes(3 * 1024 * 1024)).toBe('3.0 MB')
})
