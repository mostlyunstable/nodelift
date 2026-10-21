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

/** Connection points on the left and right edge, as on an n8n node. */
const Ports = () => (
  <>
    <Handle type="target" position={Position.Left} isConnectable={false} />
    <Handle type="source" position={Position.Right} isConnectable={false} />
  </>
)

/** A file: one box in the tree. The name is a real button, so Tab and Enter work. */
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

/** A folder: a box that opens into what it holds, or (the repository itself) the start of the tree. */
export function FolderNode({ data }: NodeProps<ExplorerNode>) {
  const toggle = useExplorer((s) => s.toggleDir)
  const isRoot = data.path === ''
  const count = `${data.count} file${data.count === 1 ? '' : 's'}`
  return (
    <div className={`xt xt-folder${data.expanded ? ' open' : ''}${isRoot ? ' root' : ''}`}>
      <Ports />
      <span className="xn-badge" aria-hidden="true">
        {isRoot ? '◆' : data.expanded ? '▾' : '▸'}
      </span>
      <div className="xt-text">
        {isRoot ? (
          <span className="xn-open xn-root-name">{data.name}</span>
        ) : (
          <button
            className="xn-open"
            aria-expanded={data.expanded}
            aria-label={`${data.expanded ? 'Collapse' : 'Expand'} ${data.name}, ${count}`}
            onClick={() => toggle(data.path)}
          >
            {data.name}
          </button>
        )}
        <div className="xt-meta">
          {count}
          {data.problems > 0 && <span className="xn-problems"> ⚠ {data.problems}</span>}
        </div>
      </div>
    </div>
  )
}
