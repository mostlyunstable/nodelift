import { Handle, Position, type NodeProps } from '@xyflow/react'
import type { FlowNode } from '../canvas/mapper'
import { useStore } from '../state/store'

export function CodeNode({ id, data, selected }: NodeProps<FlowNode>) {
  const status = useStore((s) => s.run?.nodes.find((n) => n.node_id === id))
  return (
    <div className={`code-node ${selected ? 'selected' : ''} status-${status?.status ?? 'idle'}`}>
      <Handle type="target" position={Position.Left} />
      <div className="code-node-title">
        <span className="code-node-badge">py</span>
        {data.name}
      </div>
      <div className="code-node-meta">
        {status ? `${status.status} · ${status.duration_ms}ms` : 'code.python'}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}
