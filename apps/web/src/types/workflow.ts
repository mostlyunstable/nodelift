// Backend execution format (schema_version 1). Independent of React Flow's UI state.
export interface WorkflowNode {
  id: string
  type: 'code.python'
  name: string
  config: { source: string }
}
export interface Endpoint {
  node: string
  port: string
}
export interface WorkflowEdge {
  id: string
  source: Endpoint
  target: Endpoint
}
export interface WorkflowDefinition {
  schema_version: 1
  id: string
  name: string
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  ui: { positions: Record<string, { x: number; y: number }> }
}

export interface LogLine {
  stream: 'stdout' | 'stderr'
  text: string
}
export interface NodeError {
  type: string
  message: string
  line?: number | null
  column?: number | null
  traceback?: string | null
}
export interface CodeRunResult {
  status: 'succeeded' | 'failed'
  output: unknown
  logs: LogLine[]
  duration_ms: number
  error: NodeError | null
}
export interface NodeExecution {
  node_id: string
  status: 'succeeded' | 'failed' | 'skipped'
  input: unknown
  output: unknown
  logs: LogLine[]
  error: NodeError | null
  duration_ms: number
}
export interface ExecutionRun {
  id: string
  status: 'succeeded' | 'failed'
  nodes: NodeExecution[]
  duration_ms: number
}
export interface ValidationIssue {
  code: string
  message: string
  node_id?: string | null
}
