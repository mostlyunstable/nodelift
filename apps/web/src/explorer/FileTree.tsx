import { useMemo, useRef, useState, type KeyboardEvent } from 'react'
import type { RepoFile } from '../api/client'
import { ancestorDirs } from './graph'
import { buildTree, searchFiles, type TreeDir, type TreeNode } from './tree'

interface Props {
  files: RepoFile[]
  selected: string | null
  onSelect: (path: string) => void
}

interface RowProps {
  node: TreeNode
  depth: number
  parent: string
  open: Set<string>
  toggle: (path: string, force?: boolean) => void
  selected: string | null
  onSelect: (path: string) => void
  focused: string
  setFocused: (path: string) => void
  onKey: (e: KeyboardEvent<HTMLElement>, node: TreeNode, parent: string) => void
}

function Row(p: RowProps) {
  const { node, depth } = p
  const pad = { paddingLeft: 8 + depth * 14 }
  const common = {
    'aria-level': depth + 1,
    'data-path': node.path,
    tabIndex: p.focused === node.path ? 0 : -1,
    style: pad,
    onFocus: () => p.setFocused(node.path),
    onKeyDown: (e: KeyboardEvent<HTMLElement>) => p.onKey(e, node, p.parent),
  }
  if (node.kind === 'file') {
    return (
      <li role="none">
        <button
          role="treeitem"
          {...common}
          aria-selected={p.selected === node.path}
          className={`tree-row${p.selected === node.path ? ' selected' : ''}`}
          onClick={() => p.onSelect(node.path)}
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
  const isOpen = p.open.has(node.path)
  return (
    <li role="none">
      <button
        role="treeitem"
        {...common}
        aria-selected={false}
        aria-expanded={isOpen}
        className="tree-row"
        onClick={() => p.toggle(node.path)}
      >
        <span className="tree-icon" aria-hidden="true">
          {isOpen ? '▾' : '▸'}
        </span>
        <span className="tree-name">{node.name}</span>
        <span className="tree-count" aria-label={`${node.fileCount} files`}>
          {node.fileCount}
        </span>
      </button>
      {isOpen && (
        <ul role="group" className="tree-list">
          {node.children.map((c) => (
            <Row key={c.path} {...p} node={c} depth={depth + 1} parent={node.path} />
          ))}
        </ul>
      )}
    </li>
  )
}

/** Is the item at `path` currently drawn (all of its folders are open)? */
function isVisible(root: TreeDir, open: Set<string>, path: string): boolean {
  if (!path) return false
  const parts = path.split('/')
  for (let i = 1; i < parts.length; i++) if (!open.has(parts.slice(0, i).join('/'))) return false
  return root.children.length > 0
}

/**
 * The file list. It is also the keyboard-friendly way around the graph: arrow keys move, Right/Left open and
 * close folders (or jump into/out of them), Home/End jump, Enter or Space opens the file.
 */
export function FileTree({ files, selected, onSelect }: Props) {
  const root: TreeDir = useMemo(() => buildTree(files), [files])
  const [open, setOpen] = useState<Set<string>>(() => new Set())
  const [query, setQuery] = useState('')
  const [focused, setFocused] = useState<string>('')
  const [seen, setSeen] = useState<string | null>(null)
  const tree = useRef<HTMLUListElement>(null)
  const hits = useMemo(() => searchFiles(files, query), [files, query])

  // when a file is chosen elsewhere (graph, search, a link), open its folders so it is visible here too
  if (selected !== seen) {
    setSeen(selected)
    if (selected) {
      setOpen((prev) => new Set([...prev, ...ancestorDirs(selected).filter((d) => d !== '')]))
      setFocused(selected)
    }
  }

  const toggle = (path: string, force?: boolean) =>
    setOpen((prev) => {
      const next = new Set(prev)
      const want = force ?? !next.has(path)
      if (want) next.add(path)
      else next.delete(path)
      return next
    })

  const items = () => [...(tree.current?.querySelectorAll<HTMLElement>('[role="treeitem"]') ?? [])]
  const focusPath = (path: string) => {
    setFocused(path)
    items()
      .find((el) => el.dataset.path === path)
      ?.focus()
  }

  const onKey = (e: KeyboardEvent<HTMLElement>, node: TreeNode, parent: string) => {
    const list = items()
    const at = list.findIndex((el) => el.dataset.path === node.path)
    const go = (i: number) => {
      const el = list[Math.max(0, Math.min(list.length - 1, i))]
      if (el?.dataset.path !== undefined) focusPath(el.dataset.path)
    }
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault()
        go(at + 1)
        break
      case 'ArrowUp':
        e.preventDefault()
        go(at - 1)
        break
      case 'Home':
        e.preventDefault()
        go(0)
        break
      case 'End':
        e.preventDefault()
        go(list.length - 1)
        break
      case 'ArrowRight':
        if (node.kind !== 'dir') break
        e.preventDefault()
        if (!open.has(node.path)) toggle(node.path, true)
        else go(at + 1)
        break
      case 'ArrowLeft':
        e.preventDefault()
        if (node.kind === 'dir' && open.has(node.path)) toggle(node.path, false)
        else if (parent !== '') focusPath(parent)
        break
    }
  }

  const firstPath = root.children[0]?.path ?? ''
  const tabStop = isVisible(root, open, focused) ? focused : firstPath

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
        <ul ref={tree} role="tree" aria-label="Repository files" className="tree-list">
          {root.children.map((c) => (
            <Row
              key={c.path}
              node={c}
              depth={0}
              parent=""
              open={open}
              toggle={toggle}
              selected={selected}
              onSelect={onSelect}
              focused={tabStop}
              setFocused={setFocused}
              onKey={onKey}
            />
          ))}
        </ul>
      )}
    </div>
  )
}
