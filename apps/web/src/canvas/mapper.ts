import type { Edge, Node } from '@xyflow/react'
import type { WorkflowDefinition } from '../types/workflow'

export interface CodeNodeData extends Record<string, unknown> {
  name: string
  source: string
  testInput: string
  idempotent: boolean
  maxAttempts: number // retries only apply to idempotent nodes
}

export type FlowNode = Node<CodeNodeData, 'code'>

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
      type: 'code.python',
      name: n.data.name,
      config: {
        source: n.data.source,
        ...(n.data.idempotent ? { idempotent: true } : {}),
        ...(n.data.idempotent && n.data.maxAttempts > 1
          ? { retry: { max_attempts: n.data.maxAttempts, backoff_ms: 500 } }
          : {}),
      },
    })),
    edges: edges.map((e) => ({
      id: e.id,
      source: { node: e.source, port: 'out' },
      target: { node: e.target, port: 'in' },
    })),
    ui: { positions: Object.fromEntries(nodes.map((n) => [n.id, n.position])) },
  }
}

export function fromWorkflow(wf: WorkflowDefinition): { nodes: FlowNode[]; edges: Edge[] } {
  return {
    nodes: wf.nodes.map((n, i) => ({
      id: n.id,
      type: 'code',
      position: wf.ui?.positions?.[n.id] ?? { x: 80 + i * 260, y: 120 },
      data: {
        name: n.name,
        source: n.config.source,
        testInput: '{}',
        idempotent: n.config.idempotent === true,
        maxAttempts: n.config.retry?.max_attempts ?? 1,
      },
    })),
    edges: wf.edges.map((e) => ({
      id: e.id || `${e.source.node}->${e.target.node}`,
      source: e.source.node,
      target: e.target.node,
    })),
  }
}
