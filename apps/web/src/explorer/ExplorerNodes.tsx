import { Handle, Position, type NodeProps } from '@xyflow/react'
import { useExplorer } from '../state/explorer'
import type { ExplorerNode } from './graph'
import { formatBytes } from './tree'

const BADGES: Record<string, string> = {
  python: 'py',
  javascript: 'js',
  typescript: 'ts',
  json: '{ }',
  html: '<>',
  css: 'css',
  scss: 'css',
  yaml: 'yml',
  sql: 'sql',
  shell: 'sh',
  markdown: 'md',
}

export function FileNode({ data, selected }: NodeProps<ExplorerNode>) {
  return (
    <div
      className={`xn xn-file${selected ? ' selected' : ''}${data.note ? ' unreadable' : ''}`}
      title={data.path}
    >
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <div className="xn-title">
        <span className="xn-badge" aria-hidden="true">
          {BADGES[data.language] ?? data.language.slice(0, 3)}
        </span>
        <span className="xn-name">{data.name}</span>
      </div>
      <div className="xn-meta">
        {data.note ? data.note : `${data.language} · ${data.lines} lines`} · {formatBytes(data.size)}
      </div>
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </div>
  )
}

export function DirNode({ data }: NodeProps<ExplorerNode>) {
  const toggle = useExplorer((s) => s.toggleDir)
  return (
    <div className="xn xn-dir" title={data.path || data.name}>
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <div className="xn-title">
        <button
          className="xn-toggle nodrag nopan"
          aria-expanded={data.expanded}
          aria-label={`${data.expanded ? 'Collapse' : 'Expand'} ${data.name}`}
          onClick={(e) => {
            e.stopPropagation()
            toggle(data.path)
          }}
        >
          {data.expanded ? '▾' : '▸'}
        </button>
        <span className="xn-name">{data.name}</span>
        <span className="xn-count">{data.count}</span>
      </div>
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </div>
  )
}
