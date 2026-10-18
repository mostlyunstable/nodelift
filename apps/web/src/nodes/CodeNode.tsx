import { Handle, Position, type NodeProps } from '@xyflow/react'
import type { FlowNode } from '../canvas/mapper'
import { useStore } from '../state/store'
import type { NodeLiveStatus } from '../types/workflow'

const BADGES: Record<string, string> = { 'code.python': 'py', 'transform.json': '{ }', 'http.request': 'http' }

export function CodeNode({ id, data, selected }: NodeProps<FlowNode>) {
  const done = useStore((s) => s.run?.nodes.findLast((n) => n.node_id === id))
  const live = useStore((s): NodeLiveStatus | undefined => s.liveStatus[id])
  const state: NodeLiveStatus | 'idle' = live ?? done?.status ?? 'idle'
  return (
    <div className={`code-node ${selected ? 'selected' : ''} status-${state}`}>
      <Handle type="target" position={Position.Left} />
      <div className="code-node-title">
        <span className="code-node-badge">{BADGES[data.nodeType] ?? data.nodeType.slice(0, 4)}</span>
        {data.name}
      </div>
      <div className="code-node-meta">
        {state === 'idle' ? data.nodeType : state === 'running' ? 'running…' : `${state}${done ? ` · ${done.duration_ms}ms` : ''}`}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}
