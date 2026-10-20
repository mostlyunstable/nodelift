// Backend execution format (schema_version 1). Independent of React Flow's UI state.
export interface WorkflowNode {
  id: string
  type: string
  name: string
  config: Record<string, unknown> & {
    idempotent?: boolean
    retry?: { max_attempts: number; backoff_ms: number }
  }
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
  status: 'succeeded' | 'failed' | 'skipped' | 'cancelled'
  attempt?: number
  reused?: boolean
  activated_ports?: string[] | null
  skip_reason?: string | null
  input: unknown
  output: unknown
  logs: LogLine[]
  error: NodeError | null
  duration_ms: number
}
export type RunStatus = 'running' | 'succeeded' | 'failed' | 'cancelled'
export interface ExecutionRun {
  id: string
  status: RunStatus
  nodes: NodeExecution[]
  duration_ms: number
}
export interface ValidationIssue {
  code: string
  message: string
  node_id?: string | null
}

export interface WorkflowSummary {
  id: string
  name: string
  revision: number
  updated_at: string
}
export interface WorkflowRecord {
  id: string
  name: string
  draft: WorkflowDefinition
  revision: number
}
export interface VersionSummary {
  version_no: number
  content_hash: string
  created_at: string
}
export interface RunSummary {
  id: string
  status: RunStatus
  version_no: number
  duration_ms: number
  created_at: string
}
export interface RunRecord extends ExecutionRun {
  workflow_id: string
  version_no: number
}

export type NodeLiveStatus = 'running' | NodeExecution['status']
export interface RunEvent {
  seq: number
  type: 'run.started' | 'node.started' | 'node.finished' | 'run.finished' | 'run.cancel_requested'
  created_at: string
  node_id?: string
  status?: string
  duration_ms?: number
  error_type?: string | null
  skip_reason?: string | null
  attempt?: number
  will_retry?: boolean
  reused?: boolean
  version_no?: number
  reason?: string
}

export interface NodeDefinition {
  type: string
  version: number
  title: string
  category: string
  description: string
  config_schema: Record<string, unknown>
  default_config: Record<string, unknown>
  inputs?: { name: string }[]
  outputs?: { name: string }[]
}

export interface VersionRecord {
  id: string
  workflow_id: string
  version_no: number
  content_hash: string
  definition: WorkflowDefinition
  created_at: string
}

export interface WorkflowFile {
  format: string
  format_version: number
  exported_at?: string
  workflow: { name: string; definition: unknown }
}

export interface ImportSummary {
  name: string
  nodes: number
  edges: number
  node_types: Record<string, number>
  code_nodes: number
  http_hosts: string[]
  warnings: string[]
}

export interface ImportPreview {
  valid: boolean
  issues: ValidationIssue[]
  summary: ImportSummary
}

export interface ExampleInfo {
  id: string
  title: string
  description: string
  nodes: number
}

export interface SystemInfo {
  version: string
  schema_revision: string | null
  schema_head: string
  data_dir: string
  log_dir: string | null
  backup_dir: string
  backups: string[]
  python: string
  uptime_s: number
}
