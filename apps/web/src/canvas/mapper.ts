import type { Edge, Node } from '@xyflow/react'
import type { WorkflowDefinition } from '../types/workflow'

export interface NodeData extends Record<string, unknown> {
  name: string
  nodeType: string // registry type id, e.g. "code.python"
  config: Record<string, unknown> // node-specific settings, validated by the backend
  testInput: string
  idempotent: boolean
  maxAttempts: number // retries only apply to idempotent nodes
}

export type FlowNode = Node<NodeData, 'node'>

export const DEFAULT_SOURCE =
  'def main(input_data):\n    return {"message": "Hello from Nodecraft"}\n'

/** React Flow state -> backend workflow format. Layout goes into `ui` only. */
export function toWorkflow(nodes: FlowNode[], edges: Edge[], name = 'Untitled'): WorkflowDefinition {
  return {
    schema_version: 1,
    id: '',
    name,
    nodes: nodes.map((n) => ({
      id: n.id,
      type: n.data.nodeType,
      name: n.data.name,
      config: {
        ...n.data.config,
        ...(n.data.idempotent ? { idempotent: true } : {}),
        ...(n.data.idempotent && n.data.maxAttempts > 1
          ? { retry: { max_attempts: n.data.maxAttempts, backoff_ms: 500 } }
          : {}),
      },
    })),
    edges: edges.map((e) => ({
      id: e.id,
      source: { node: e.source, port: e.sourceHandle ?? 'out' },
      target: { node: e.target, port: e.targetHandle ?? 'in' },
    })),
    ui: { positions: Object.fromEntries(nodes.map((n) => [n.id, n.position])) },
  }
}

export function fromWorkflow(wf: WorkflowDefinition): { nodes: FlowNode[]; edges: Edge[] } {
  return {
    nodes: wf.nodes.map((n, i) => {
      const { idempotent, retry, ...config } = n.config
      return {
        id: n.id,
        type: 'node',
        position: wf.ui?.positions?.[n.id] ?? { x: 80 + i * 260, y: 120 },
        data: {
          name: n.name,
          nodeType: n.type,
          config,
          testInput: '{}',
          idempotent: idempotent === true,
          maxAttempts: retry?.max_attempts ?? 1,
        },
      }
    }),
    edges: wf.edges.map((e) => ({
      id: e.id || `${e.source.node}:${e.source.port}->${e.target.node}`,
      source: e.source.node,
      target: e.target.node,
      sourceHandle: e.source.port,
      targetHandle: e.target.port,
      ...(e.source.port !== 'out' ? { label: e.source.port } : {}), // name the branch an edge leaves from
    })),
  }
}
