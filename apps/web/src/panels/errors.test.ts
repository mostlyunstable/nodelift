import { describe, expect, it } from 'vitest'
import type { NodeError, NodeExecution } from '../types/workflow'
import { errorLine, explainError, firstFailedNodeId } from './errors'

const tb = (...lines: number[]) =>
  `Traceback (most recent call last):\n${lines.map((n) => `  File "<node>", line ${n}, in main\n    code\n`).join('')}ZeroDivisionError: x`

describe('errorLine', () => {
  it('uses the syntax-error position', () =>
    expect(errorLine({ type: 'syntax_error', message: 'm', line: 4 })).toBe(4))
  it('uses the LAST user frame of a traceback (where it actually failed)', () => {
    expect(errorLine({ type: 'runtime_error', message: 'm', traceback: tb(2, 7, 9) })).toBe(9)
  })
  it('is null when there is nothing to point at', () => {
    expect(errorLine(null)).toBeNull()
    expect(errorLine({ type: 'timeout', message: 'm' })).toBeNull()
    expect(errorLine({ type: 'runtime_error', message: 'm', traceback: 'no frames here' })).toBeNull()
  })
})

describe('explainError', () => {
  const runtime = (message: string, line?: number): NodeError => ({
    type: 'runtime_error',
    message,
    traceback: line ? tb(line) : null,
  })
  it('explains common Python errors in plain language and keeps the line number', () => {
    expect(explainError(runtime('ZeroDivisionError: float division by zero', 3))).toBe(
      'Something was divided by zero (line 3).',
    )
    expect(explainError(runtime("KeyError: 'price'", 5))).toContain("not in the data ('price')")
    expect(explainError(runtime("ModuleNotFoundError: No module named 'requests'"))).toContain(
      'standard library',
    )
    expect(explainError(runtime('IndexError: list index out of range'))).toContain('past the end of a list')
  })
  it('falls back to the exception name for unknown errors', () => {
    expect(explainError(runtime('CustomThing: bad stuff'))).toBe('The code raised CustomThing: bad stuff.')
    expect(explainError(runtime('plain message with no exception name'))).toContain('plain message')
  })
  it('covers every error type the backend can return', () => {
    const types = [
      'syntax_error',
      'missing_main',
      'runtime_error',
      'invalid_output',
      'output_too_large',
      'timeout',
      'cancelled',
      'worker_crashed',
      'invalid_config',
      'transform_error',
      'blocked_request',
      'network_error',
      'http_error',
      'response_too_large',
    ]
    for (const type of types) {
      const text = explainError({ type, message: 'detail' })
      expect(text.length, type).toBeGreaterThan(10)
    }
    expect(explainError({ type: 'syntax_error', message: 'invalid syntax', line: 2 })).toBe(
      'The code has a syntax error on line 2: invalid syntax.',
    )
    expect(explainError({ type: 'something_new', message: 'raw' })).toBe('raw')
  })
})

describe('firstFailedNodeId', () => {
  const rec = (node_id: string, status: NodeExecution['status'], attempt = 1): NodeExecution => ({
    node_id,
    status,
    attempt,
    input: null,
    output: null,
    logs: [],
    error: null,
    duration_ms: 1,
  })
  it('finds the first failed node in run order', () => {
    expect(
      firstFailedNodeId({ nodes: [rec('a', 'succeeded'), rec('b', 'failed'), rec('c', 'skipped')] }),
    ).toBe('b')
  })
  it('ignores a node that failed but then succeeded on retry', () => {
    expect(
      firstFailedNodeId({ nodes: [rec('a', 'failed', 1), rec('a', 'succeeded', 2), rec('b', 'failed')] }),
    ).toBe('b')
  })
  it('is null for a clean run, an empty run or no run', () => {
    expect(firstFailedNodeId({ nodes: [rec('a', 'succeeded')] })).toBeNull()
    expect(firstFailedNodeId({ nodes: [] })).toBeNull()
    expect(firstFailedNodeId(null)).toBeNull()
  })
})
