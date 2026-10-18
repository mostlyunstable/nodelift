import type {
  CodeRunResult,
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
  const res = await fetch(`/api/v1${path}`, {
    method,
    headers: body === undefined ? undefined : { 'content-type': 'application/json' },
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
  testCode: (source: string, input: unknown, signal?: AbortSignal) =>
    request<CodeRunResult>('POST', '/nodes/code/test', { source, input }, signal),
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
  getRun: (runId: string) => request<RunRecord>('GET', `/runs/${runId}`),
  listEvents: async (runId: string, after = 0) => {
    const rows = await request<{ seq: number; type: RunEvent['type']; created_at: string; payload: Record<string, unknown> }[]>(
      'GET',
      `/runs/${runId}/events?after=${after}`,
    )
    return rows.map((r) => ({ seq: r.seq, type: r.type, created_at: r.created_at, ...r.payload }) as RunEvent)
  },
}
