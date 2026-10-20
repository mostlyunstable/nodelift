import { Handle, Position, type NodeProps } from '@xyflow/react'
import { useId } from 'react'
import { useExplorer } from '../state/explorer'
import type { ExplorerNode } from './graph'
import { formatBytes } from './tree'

const BADGES: Record<string, string> = {
  python: 'py', javascript: 'js', typescript: 'ts', json: '{ }', html: '<>', css: 'css', scss: 'css',
  yaml: 'yml', sql: 'sql', shell: 'sh', markdown: 'md', plaintext: 'txt', go: 'go', java: 'java',
  rust: 'rs', ruby: 'rb',
} // prettier-ignore

const Ports = () => (
  <>
    <Handle type="target" position={Position.Left} isConnectable={false} />
    <Handle type="source" position={Position.Right} isConnectable={false} />
  </>
)

/** A file: one tile in its folder's grid. The name is a real button, so Tab and Enter work. */
export function FileNode({ data, selected }: NodeProps<ExplorerNode>) {
  const metaId = useId()
  return (
    <div
      className={`xt xt-file${selected ? ' selected' : ''}${data.note ? ' unreadable' : ''}`}
      title={data.path}
    >
      <Ports />
      <span className="xn-badge" aria-hidden="true">
        {BADGES[data.language] ?? data.language.slice(0, 3)}
      </span>
      <div className="xt-text">
        <button
          className="xn-open"
          aria-pressed={selected}
          aria-describedby={metaId}
          onClick={() => void useExplorer.getState().selectFile(data.path)}
        >
          {data.name}
        </button>
        <div id={metaId} className="xt-meta">
          {data.note ? data.note : `${data.lines} lines`} · {formatBytes(data.size)}
          {data.problems > 0 && (
            <span className="xn-problems">
              {' '}
              ⚠ {data.problems}
              <span className="visually-hidden"> problem{data.problems === 1 ? '' : 's'}</span>
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

/** A collapsed folder: a tile that opens into a card of its own. */
export function FolderTile({ data }: NodeProps<ExplorerNode>) {
  const toggle = useExplorer((s) => s.toggleDir)
  return (
    <div className="xt xt-folder">
      <Ports />
      <span className="xt-folder-icon" aria-hidden="true">
        ▸
      </span>
      <div className="xt-text">
        <button
          className="xn-open nodrag nopan"
          aria-expanded={false}
          aria-label={`Expand ${data.name}, ${data.count} files`}
          onClick={() => toggle(data.path)}
        >
          {data.name}
        </button>
        <div className="xt-meta">
          {data.count} file{data.count === 1 ? '' : 's'}
          {data.problems > 0 && <span className="xn-problems"> ⚠ {data.problems}</span>}
        </div>
      </div>
    </div>
  )
}

/** An open folder: a titled card holding its tiles and its sub-folder cards. */
export function CardNode({ data }: NodeProps<ExplorerNode>) {
  const toggle = useExplorer((s) => s.toggleDir)
  const isRoot = data.path === ''
  return (
    <div className={`xg${isRoot ? ' xg-root' : ''}`}>
      <Ports />
      <div className="xg-head">
        {isRoot ? (
          <span className="xg-title">{data.name}</span>
        ) : (
          <button
            className="xg-toggle nodrag nopan"
            aria-expanded={true}
            aria-label={`Collapse ${data.name}, ${data.count} files`}
            onClick={() => toggle(data.path)}
          >
            <span aria-hidden="true">▾ </span>
            <span className="xg-title">{data.name}</span>
          </button>
        )}
        <span className="xn-count">
          {data.count} file{data.count === 1 ? '' : 's'}
        </span>
        {data.problems > 0 && <span className="xn-problems">⚠ {data.problems}</span>}
      </div>
    </div>
  )
}
