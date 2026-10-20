import type { ExecutionRun, NodeError } from '../types/workflow'

/** The line in the user's code where it failed, from a syntax error position or the last traceback frame. */
export function errorLine(error: NodeError | null | undefined): number | null {
  if (!error) return null
  if (error.line != null) return error.line
  if (!error.traceback) return null
  const matches = [...error.traceback.matchAll(/File "<node>", line (\d+)/g)]
  return matches.length > 0 ? Number(matches[matches.length - 1][1]) : null
}

const PYTHON_ERRORS: Record<string, (detail: string) => string> = {
  ZeroDivisionError: () => 'Something was divided by zero',
  KeyError: (d) => `The code looked up a key that is not in the data (${d})`,
  IndexError: () => 'The code read past the end of a list',
  TypeError: (d) => `A value had the wrong type: ${d}`,
  ValueError: (d) => `A value was not acceptable: ${d}`,
  NameError: (d) => `The code used a name that is not defined: ${d}`,
  AttributeError: (d) => `The code used something a value does not have: ${d}`,
  ModuleNotFoundError: (d) => `That module is not available (only the Python standard library is): ${d}`,
  ImportError: (d) => `That import failed (only the Python standard library is available): ${d}`,
  AssertionError: () => 'An assertion in the code failed',
  RecursionError: () => 'The code recursed too deeply',
  MemoryError: () => 'The code ran out of memory',
  PermissionError: (d) =>
    `The code was not allowed to do that (${d}). Code nodes are confined: no network unless “Allow network access” is ticked, and no access to your home folder.`,
}

/** A plain-language sentence for a failed node, with the technical message still available below it. */
export function explainError(error: NodeError): string {
  const line = errorLine(error)
  const where = line != null ? ` (line ${line})` : ''
  switch (error.type) {
    case 'syntax_error':
      return `The code has a syntax error${line != null ? ` on line ${line}` : ''}: ${error.message}.`
    case 'missing_main':
      return 'The code must define a function named main(input_data).'
    case 'runtime_error': {
      const m = /^(\w+(?:\.\w+)*): ?([\s\S]*)$/.exec(error.message)
      const name = m?.[1].split('.').pop() ?? ''
      const detail = m?.[2] ?? error.message
      const friendly = PYTHON_ERRORS[name]
      return `${friendly ? friendly(detail) : `The code raised ${name || 'an error'}: ${detail}`}${where}.`
    }
    case 'invalid_output':
      return `The result is not valid JSON data: ${error.message}`
    case 'output_too_large':
      return 'The node returned more data than the 5 MB limit.'
    case 'timeout':
      return `The node took too long and was stopped. ${error.message}.`
    case 'memory_limit':
      return `The node used too much memory and was stopped. ${error.message}.`
    case 'cancelled':
      return 'The run was cancelled while this node was working.'
    case 'worker_crashed':
      return 'The process running this node ended unexpectedly.'
    case 'invalid_config':
      return `The node settings are not valid: ${error.message}`
    case 'transform_error':
      return `This node could not use the data it received: ${error.message}. Check that it is connected to a node that produces what it expects.`
    case 'blocked_request':
      return 'The request was blocked: nodes can only reach public internet addresses.'
    case 'network_error':
      return `The request could not be completed: ${error.message}`
    case 'http_error':
      return `The server answered with an error: ${error.message}`
    case 'missing_credential':
      return `${error.message}`
    case 'secrets_unavailable':
      return `Saved credentials could not be read: ${error.message}`
    case 'response_too_large':
      return `The response was larger than allowed: ${error.message}`
    default:
      return error.message
  }
}

/** The first node (in run order) whose final attempt failed, or null. */
export function firstFailedNodeId(run: Pick<ExecutionRun, 'nodes'> | null | undefined): string | null {
  if (!run) return null
  const last = new Map<string, string>()
  const order: string[] = []
  for (const n of run.nodes) {
    if (!last.has(n.node_id)) order.push(n.node_id)
    last.set(n.node_id, n.status)
  }
  return order.find((id) => last.get(id) === 'failed') ?? null
}
