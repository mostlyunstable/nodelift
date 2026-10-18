import type {
  CodeRunResult,
  ExecutionRun,
  ValidationIssue,
  WorkflowDefinition,
} from '../types/workflow'

export class ApiError extends Error {
  constructor(
    message: string,
    public details: ValidationIssue[] = [],
  ) {
    super(message)
  }
}

async function post<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    const err = data?.error
    throw new ApiError(err?.message ?? `Request failed (${res.status})`, err?.details ?? [])
  }
  return data as T
}

export const api = {
  testCode: (source: string, input: unknown, signal?: AbortSignal) =>
    post<CodeRunResult>('/nodes/code/test', { source, input }, signal),
  runWorkflow: (workflow: WorkflowDefinition, input: unknown, signal?: AbortSignal) =>
    post<ExecutionRun>('/runs', { workflow, input }, signal),
  validate: (workflow: WorkflowDefinition) =>
    post<{ valid: boolean; issues: ValidationIssue[] }>('/workflows/validate', workflow),
}
