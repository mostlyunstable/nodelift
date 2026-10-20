import { apiUrl, authHeaders } from './config'
import type {
  CodeRunResult,
  ExampleInfo,
  ImportPreview,
  SystemInfo,
  VersionRecord,
  WorkflowFile,
  NodeDefinition,
  RunEvent,
  RunRecord,
  RunSummary,
  ValidationIssue,
  VersionSummary,
  WorkflowDefinition,
  WorkflowRecord,
  WorkflowSummary,
} from '../types/workflow'

export class ApiError extends Error {
  constructor(
    message: string,
    public status = 0,
    public code = '',
    public details: ValidationIssue[] = [],
  ) {
    super(message)
  }
}

async function request<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const res = await fetch(apiUrl(path), {
    method,
    headers: authHeaders(body === undefined ? {} : { 'content-type': 'application/json' }),
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  })
  const data = res.status === 204 ? null : await res.json().catch(() => null)
  if (!res.ok) {
    const err = data?.error
    throw new ApiError(err?.message ?? `Request failed (${res.status})`, res.status, err?.code, err?.details ?? [])
  }
  return data as T
}

export const api = {
  nodeDefinitions: () => request<NodeDefinition[]>('GET', '/nodes/definitions'),
  testNode: (type: string, config: unknown, input: unknown, signal?: AbortSignal) =>
    request<CodeRunResult>('POST', '/nodes/test', { type, config, input }, signal),
  validate: (workflow: WorkflowDefinition) =>
    request<{ valid: boolean; issues: ValidationIssue[] }>('POST', '/workflows/validate', workflow),
  listWorkflows: () => request<WorkflowSummary[]>('GET', '/workflows'),
  getWorkflow: (id: string) => request<WorkflowRecord>('GET', `/workflows/${id}`),
  createWorkflow: (name: string, definition: WorkflowDefinition) =>
    request<WorkflowRecord>('POST', '/workflows', { name, definition }),
  updateWorkflow: (id: string, name: string, definition: WorkflowDefinition, revision: number) =>
    request<WorkflowRecord>('PUT', `/workflows/${id}`, { name, definition, revision }),
  deleteWorkflow: (id: string) => request<null>('DELETE', `/workflows/${id}`),
  createVersion: (id: string) => request<{ version_no: number }>('POST', `/workflows/${id}/versions`),
  listVersions: (id: string) => request<VersionSummary[]>('GET', `/workflows/${id}/versions`),
  startRun: (id: string, input: unknown, signal?: AbortSignal) =>
    request<RunRecord>('POST', `/workflows/${id}/runs`, { input }, signal),
  listRuns: (id: string) => request<RunSummary[]>('GET', `/workflows/${id}/runs`),
  cancelRun: (runId: string) => request<RunRecord>('POST', `/runs/${runId}/cancel`),
  resumeRun: (runId: string) => request<RunRecord>('POST', `/runs/${runId}/resume`, {}),
  getRun: (runId: string) => request<RunRecord>('GET', `/runs/${runId}`),
  getVersion: (id: string, versionNo: number) =>
    request<VersionRecord>('GET', `/workflows/${id}/versions/${versionNo}`),
  /** All events after `after`, following the server's paging headers. */
  listEvents: async (runId: string, after = 0) => {
    type Row = { seq: number; type: RunEvent['type']; created_at: string; payload: Record<string, unknown> }
    const out: RunEvent[] = []
    for (let page = 0; page < 100; page++) {
      const res = await fetch(apiUrl(`/runs/${runId}/events?after=${after}&limit=500`), { headers: authHeaders() })
      if (!res.ok) {
        const err = (await res.json().catch(() => null))?.error
        throw new ApiError(err?.message ?? `Request failed (${res.status})`, res.status, err?.code, err?.details ?? [])
      }
      const rows = (await res.json()) as Row[]
      out.push(...rows.map((r) => ({ seq: r.seq, type: r.type, created_at: r.created_at, ...r.payload }) as RunEvent))
      if (res.headers.get('x-has-more') !== '1') break
      after = Number(res.headers.get('x-next-after'))
    }
    return out
  },
  exportWorkflow: (id: string) => request<WorkflowFile>('GET', `/workflows/${id}/export`),
  exportEverything: () => request<unknown>('GET', '/system/export'),
  previewImport: (file: unknown) => request<ImportPreview>('POST', '/workflows/import/preview', file),
  importWorkflow: (file: unknown) => request<WorkflowRecord>('POST', '/workflows/import', file),
  listExamples: () => request<ExampleInfo[]>('GET', '/examples'),
  createExample: (id: string) => request<WorkflowRecord>('POST', `/examples/${id}/create`),
  systemInfo: () => request<SystemInfo>('GET', '/system/info'),
  systemLogs: (lines = 200) => request<{ path: string | null; lines: string[] }>('GET', `/system/logs?lines=${lines}`),
}
