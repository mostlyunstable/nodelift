import type { RepoFile } from '../api/client'

export interface TreeDir {
  kind: 'dir'
  name: string
  path: string
  children: TreeNode[]
  fileCount: number
}
export interface TreeFile {
  kind: 'file'
  name: string
  path: string
  file: RepoFile
}
export type TreeNode = TreeDir | TreeFile

/** Build a folder tree from flat paths. Folders sort before files; names sort case-insensitively. */
export function buildTree(files: RepoFile[]): TreeDir {
  const root: TreeDir = { kind: 'dir', name: '', path: '', children: [], fileCount: 0 }
  const dirs = new Map<string, TreeDir>([['', root]])
  for (const file of files) {
    const parts = file.path.split('/')
    let parent = root
    for (let i = 0; i < parts.length - 1; i++) {
      const path = parts.slice(0, i + 1).join('/')
      let dir = dirs.get(path)
      if (!dir) {
        dir = { kind: 'dir', name: parts[i]!, path, children: [], fileCount: 0 }
        dirs.set(path, dir)
        parent.children.push(dir)
      }
      dir.fileCount++
      parent = dir
    }
    root.fileCount++
    parent.children.push({ kind: 'file', name: parts[parts.length - 1]!, path: file.path, file })
  }
  const sort = (d: TreeDir) => {
    d.children.sort((a, b) =>
      a.kind !== b.kind
        ? a.kind === 'dir'
          ? -1
          : 1
        : a.name.toLowerCase().localeCompare(b.name.toLowerCase()),
    )
    for (const c of d.children) if (c.kind === 'dir') sort(c)
  }
  sort(root)
  return root
}

/** Case-insensitive substring match on the full path. Returns at most `limit` matches. */
export function searchFiles(files: RepoFile[], query: string, limit = 200): RepoFile[] {
  const q = query.trim().toLowerCase()
  if (!q) return []
  const out: RepoFile[] = []
  for (const f of files) {
    if (f.path.toLowerCase().includes(q)) {
      out.push(f)
      if (out.length >= limit) break
    }
  }
  return out
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}
