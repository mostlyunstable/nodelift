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

/** A steady colour per language, so the same kind of file looks the same everywhere. */
const hueOf = (language: string): number => {
  let h = 0
  for (const c of language) h = (h * 31 + c.charCodeAt(0)) % 360
  return h
}

/** Invisible connection points at the centre of the node, so lines run from circle to circle. */
const Ports = () => (
  <>
    <Handle type="target" position={Position.Left} isConnectable={false} className="xn-port" />
    <Handle type="source" position={Position.Right} isConnectable={false} className="xn-port" />
  </>
)

/** A file: a round node sized by its length. The name under it is a real button, so Tab and Enter work. */
export function FileNode({ data, selected }: NodeProps<ExplorerNode>) {
  const metaId = useId()
  const open = () => void useExplorer.getState().selectFile(data.path)
  return (
    <div
      className={`xt xt-file${selected ? ' selected' : ''}${data.note ? ' unreadable' : ''}`}
      title={data.path}
      style={{ ['--hue' as string]: hueOf(data.language) }}
    >
      <Ports />
      <button className="xn-dot" tabIndex={-1} aria-hidden="true" onClick={open}>
        {BADGES[data.language] ?? data.language.slice(0, 3)}
        {data.problems > 0 && <span className="xn-warn">!</span>}
      </button>
      <div className="xn-label">
        <button className="xn-open" aria-pressed={selected} aria-describedby={metaId} onClick={open}>
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

/** A folder: a hub that opens into its files and sub-folders, or (the repository itself) the centre of the network. */
export function FolderNode({ data }: NodeProps<ExplorerNode>) {
  const toggle = useExplorer((s) => s.toggleDir)
  const isRoot = data.path === ''
  const count = `${data.count} file${data.count === 1 ? '' : 's'}`
  return (
    <div className={`xt xt-folder${data.expanded ? ' open' : ''}${isRoot ? ' root' : ''}`}>
      <Ports />
      <button
        className="xn-dot"
        tabIndex={-1}
        aria-hidden="true"
        disabled={isRoot}
        onClick={() => toggle(data.path)}
      >
        {data.count}
      </button>
      <div className="xn-label">
        {isRoot ? (
          <span className="xn-open xn-root-name">{data.name}</span>
        ) : (
          <button
            className="xn-open"
            aria-expanded={data.expanded}
            aria-label={`${data.expanded ? 'Collapse' : 'Expand'} ${data.name}, ${count}`}
            onClick={() => toggle(data.path)}
          >
            {data.expanded ? '▾ ' : '▸ '}
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
