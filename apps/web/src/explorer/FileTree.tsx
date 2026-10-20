import { useMemo, useState } from 'react'
import type { RepoFile } from '../api/client'
import { buildTree, searchFiles, type TreeDir, type TreeNode } from './tree'

interface Props {
  files: RepoFile[]
  selected: string | null
  onSelect: (path: string) => void
}

function Row({
  node,
  depth,
  open,
  toggle,
  selected,
  onSelect,
}: {
  node: TreeNode
  depth: number
  open: Set<string>
  toggle: (path: string) => void
  selected: string | null
  onSelect: (path: string) => void
}) {
  const pad = { paddingLeft: 8 + depth * 14 }
  if (node.kind === 'file') {
    return (
      <li role="none">
        <button
          role="treeitem"
          aria-selected={selected === node.path}
          className={`tree-row${selected === node.path ? ' selected' : ''}`}
          style={pad}
          onClick={() => onSelect(node.path)}
          title={node.path}
        >
          <span className="tree-icon" aria-hidden="true">
            {node.file.binary || node.file.skip_reason ? '▫' : '▪'}
          </span>
          <span className="tree-name">{node.name}</span>
        </button>
      </li>
    )
  }
  const isOpen = open.has(node.path)
  return (
    <li role="none">
      <button
        role="treeitem"
        aria-selected={false}
        aria-expanded={isOpen}
        className="tree-row"
        style={pad}
        onClick={() => toggle(node.path)}
      >
        <span className="tree-icon" aria-hidden="true">
          {isOpen ? '▾' : '▸'}
        </span>
        <span className="tree-name">{node.name}</span>
        <span className="tree-count">{node.fileCount}</span>
      </button>
      {isOpen && (
        <ul role="group" className="tree-list">
          {node.children.map((c) => (
            <Row
              key={c.path}
              node={c}
              depth={depth + 1}
              open={open}
              toggle={toggle}
              selected={selected}
              onSelect={onSelect}
            />
          ))}
        </ul>
      )}
    </li>
  )
}

export function FileTree({ files, selected, onSelect }: Props) {
  const root: TreeDir = useMemo(() => buildTree(files), [files])
  const [open, setOpen] = useState<Set<string>>(() => new Set())
  const [query, setQuery] = useState('')
  const hits = useMemo(() => searchFiles(files, query), [files, query])
  const toggle = (path: string) =>
    setOpen((prev) => {
      const next = new Set(prev)
      if (!next.delete(path)) next.add(path)
      return next
    })

  return (
    <div className="file-tree">
      <input
        className="tree-search"
        type="search"
        placeholder="Search files…"
        aria-label="Search files"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {query.trim() ? (
        <ul role="listbox" aria-label="Search results" className="tree-list">
          {hits.length === 0 && <li className="muted tree-empty">No files match “{query.trim()}”.</li>}
          {hits.map((f) => (
            <li key={f.path} role="none">
              <button
                role="option"
                aria-selected={selected === f.path}
                className={`tree-row${selected === f.path ? ' selected' : ''}`}
                onClick={() => onSelect(f.path)}
                title={f.path}
              >
                <span className="tree-name">{f.path}</span>
              </button>
            </li>
          ))}
          {hits.length >= 200 && <li className="muted tree-empty">Showing the first 200 matches.</li>}
        </ul>
      ) : (
        <ul role="tree" aria-label="Repository files" className="tree-list">
          {root.children.map((c) => (
            <Row
              key={c.path}
              node={c}
              depth={0}
              open={open}
              toggle={toggle}
              selected={selected}
              onSelect={onSelect}
            />
          ))}
        </ul>
      )}
    </div>
  )
}
