import { Handle, Position, type NodeProps } from '@xyflow/react'
import type { FlowNode } from '../canvas/mapper'
import { useStore } from '../state/store'
import type { NodeLiveStatus } from '../types/workflow'

const BADGES: Record<string, string> = {
  'code.python': 'py',
  'transform.json': '{ }',
  'http.request': 'http',
  'logic.branch': 'if',
}

const SKIP_TEXT: Record<string, string> = {
  branch_not_taken: 'not taken',
  upstream_failed: 'upstream failed',
  run_stopped: 'run stopped',
}

export function CodeNode({ id, data, selected }: NodeProps<FlowNode>) {
  const done = useStore((s) => s.run?.nodes.findLast((n) => n.node_id === id))
  const live = useStore((s): NodeLiveStatus | undefined => s.liveStatus[id])
  const outputs = useStore((s) => s.nodeDefs.find((d) => d.type === data.nodeType)?.outputs)
  const state: NodeLiveStatus | 'idle' = live ?? done?.status ?? 'idle'
  const ports = outputs && outputs.length > 0 ? outputs.map((p) => p.name) : data.nodeType === 'logic.branch' ? ['true', 'false'] : ['out']
  const fired = done?.activated_ports ?? null

  let meta: string
  if (state === 'idle') meta = data.nodeType
  else if (state === 'running') meta = 'running…'
  else if (state === 'skipped') meta = `skipped${done?.skip_reason ? ` · ${SKIP_TEXT[done.skip_reason] ?? done.skip_reason}` : ''}`
  else meta = `${state}${done ? ` · ${done.duration_ms}ms` : ''}${fired && fired.length === 1 ? ` · ${fired[0]}` : ''}`

  return (
    <div className={`code-node ${selected ? 'selected' : ''} status-${state} ${ports.length > 1 ? 'multi-port' : ''}`}>
      <Handle type="target" position={Position.Left} id="in" />
      <div className="code-node-title">
        <span className="code-node-badge">{BADGES[data.nodeType] ?? data.nodeType.slice(0, 4)}</span>
        {data.name}
      </div>
      <div className="code-node-meta">{meta}</div>
      {ports.map((port, i) => (
        <Handle
          key={port}
          type="source"
          position={Position.Right}
          id={port}
          style={ports.length > 1 ? { top: `${((i + 1) * 100) / (ports.length + 1)}%` } : undefined}
          title={ports.length > 1 ? `Output when ${port}` : undefined}
        >
          {ports.length > 1 && <span className={`port-label ${fired && !fired.includes(port) ? 'dim' : ''}`}>{port}</span>}
        </Handle>
      ))}
    </div>
  )
}
