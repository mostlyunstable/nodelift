import { useState } from 'react'
import { JsonField } from '../editor/JsonField'
import type { FlowNode } from '../canvas/mapper'
import { useStore } from '../state/store'

type Schema = {
  type?: string
  enum?: unknown[]
  title?: string
  description?: string
  minimum?: number
  maximum?: number
  default?: unknown
  properties?: Record<string, Schema>
}

/** Plain-language help for fields, because a JSON schema alone does not say what a field is for. */
const HINTS: Record<string, string> = {
  'data.filter.items_path':
    'Where the list is in the input: $ for the whole input, or a path such as $.people',
  'data.filter.match': 'Keep an item when all, or any, of the conditions match',
  'data.filter.where': 'Each path starts at the item itself ($), for example $.age',
  'text.template.template': 'Write {{ $.field }} wherever a value from the input should go',
  'text.template.escape_html': 'Turn on when building HTML, so values cannot inject markup',
  'text.template.strict': 'Fail when a placeholder has no value, instead of leaving it empty',
  'data.csv.mode': 'Parse turns CSV text into rows; write turns a list of objects into CSV text',
  'data.csv.path': 'Where the CSV text (parse) or the list of objects (write) is in the input',
  'data.csv.header': 'The first row holds the column names',
  'file.read.path': 'A file inside Nodecraft’s files folder, e.g. notes/input.txt',
  'file.write.path': 'A file inside Nodecraft’s files folder; folders are created for you',
  'file.write.content_path': 'Which part of the input to write; objects are saved as JSON',
  'file.write.append': 'Add to the end of the file instead of replacing it',
  'db.sqlite.db': 'A SQLite file inside Nodecraft’s files folder',
  'db.sqlite.sql': 'One statement. Use ? for values and list them under params',
  'db.sqlite.params': 'Values for the ? marks, as a JSON list',
  'db.sqlite.allow_write': 'Off: read-only. On: INSERT, UPDATE and DELETE are allowed',
  'ai.claude.prompt':
    'What to ask. {{ $.field }} inserts data from the previous node. The prompt is sent to Anthropic.',
  'ai.claude.credential':
    'The name of the saved credential that holds your Anthropic API key (⋯ → Credentials)',
  'ai.claude.system': 'Optional instructions that set the tone or role',
}

const LONG_TEXT = new Set(['prompt', 'template', 'sql', 'system'])
const OPS: [string, string][] = [
  ['eq', 'equals'], ['ne', 'does not equal'], ['gt', 'is greater than'], ['gte', 'is at least'],
  ['lt', 'is less than'], ['lte', 'is at most'], ['contains', 'contains'], ['in', 'is one of'],
  ['exists', 'exists'], ['not_exists', 'does not exist'],
] // prettier-ignore

const humanize = (k: string) => k.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())

interface Condition {
  path: string
  op: string
  value?: unknown
}

function Conditions({ value, onChange }: { value: Condition[]; onChange: (v: Condition[]) => void }) {
  const set = (i: number, patch: Partial<Condition>) =>
    onChange(value.map((c, j) => (j === i ? { ...c, ...patch } : c)))
  return (
    <div className="conditions">
      {value.map((c, i) => (
        <div key={i} className="condition-row">
          <input
            aria-label={`Condition ${i + 1} path`}
            value={c.path}
            placeholder="$.field"
            onChange={(e) => set(i, { path: e.target.value })}
          />
          <select
            aria-label={`Condition ${i + 1} operator`}
            value={c.op}
            onChange={(e) => set(i, { op: e.target.value })}
          >
            {OPS.map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </select>
          {c.op !== 'exists' && c.op !== 'not_exists' && (
            <input
              aria-label={`Condition ${i + 1} value`}
              value={typeof c.value === 'string' ? c.value : JSON.stringify(c.value ?? '')}
              placeholder="value"
              onChange={(e) => {
                let v: unknown = e.target.value
                try {
                  v = JSON.parse(e.target.value) // numbers, true/false, lists; anything else stays text
                } catch {
                  /* plain text */
                }
                set(i, { value: v })
              }}
            />
          )}
          <button
            aria-label={`Remove condition ${i + 1}`}
            className="icon-button"
            onClick={() => onChange(value.filter((_, j) => j !== i))}
          >
            ×
          </button>
        </div>
      ))}
      <button onClick={() => onChange([...value, { path: '$.', op: 'eq', value: '' }])}>Add condition</button>
    </div>
  )
}

/** A form generated from the node's own config schema, with an escape hatch to raw JSON. */
export function SchemaForm({ node }: { node: FlowNode }) {
  const { updateData, nodeDefs } = useStore()
  const [raw, setRaw] = useState(false)
  const def = nodeDefs.find((d) => d.type === node.data.nodeType)
  const props = (def?.config_schema as Schema | undefined)?.properties
  const required = new Set((def?.config_schema as { required?: string[] } | undefined)?.required ?? [])
  const config = node.data.config
  const setKey = (key: string, value: unknown) => updateData(node.id, { config: { ...config, [key]: value } })

  if (!props || raw)
    return (
      <>
        <JsonField
          key={node.id}
          label="Settings (JSON)"
          value={config}
          rows={10}
          onChange={(v) => updateData(node.id, { config: (v as Record<string, unknown>) ?? {} })}
        />
        {props && (
          <button className="link-button" onClick={() => setRaw(false)}>
            Back to the form
          </button>
        )}
      </>
    )

  return (
    <div className="schema-form">
      {def?.description && <p className="muted small">{def.description}</p>}
      {Object.entries(props).map(([key, schema]) => {
        const hint = HINTS[`${node.data.nodeType}.${key}`] ?? schema.description
        const label = `${schema.title ?? humanize(key)}${required.has(key) ? ' *' : ''}`
        const value = config[key] ?? schema.default
        const id = `f-${node.id}-${key}`
        let control: React.ReactNode
        if (node.data.nodeType === 'data.filter' && key === 'where') {
          control = (
            <Conditions
              value={Array.isArray(value) ? (value as Condition[]) : []}
              onChange={(v) => setKey(key, v)}
            />
          )
        } else if (schema.type === 'boolean') {
          return (
            <div key={key} className="field">
              <label className="check">
                <input
                  type="checkbox"
                  checked={value === true}
                  onChange={(e) => setKey(key, e.target.checked)}
                />{' '}
                {label}
              </label>
              {hint && <span className="muted small">{hint}</span>}
            </div>
          )
        } else if (schema.enum) {
          control = (
            <select id={id} value={String(value ?? '')} onChange={(e) => setKey(key, e.target.value)}>
              {schema.enum.map((o) => (
                <option key={String(o)} value={String(o)}>
                  {String(o)}
                </option>
              ))}
            </select>
          )
        } else if (schema.type === 'integer' || schema.type === 'number') {
          control = (
            <input
              id={id}
              type="number"
              min={schema.minimum}
              max={schema.maximum}
              value={value === undefined ? '' : Number(value)}
              onChange={(e) => setKey(key, e.target.value === '' ? undefined : Number(e.target.value))}
            />
          )
        } else if (schema.type === 'string') {
          control = LONG_TEXT.has(key) ? (
            <textarea
              id={id}
              rows={5}
              value={String(value ?? '')}
              onChange={(e) => setKey(key, e.target.value)}
            />
          ) : (
            <input id={id} value={String(value ?? '')} onChange={(e) => setKey(key, e.target.value)} />
          )
        } else {
          control = (
            <JsonField
              key={`${node.id}-${key}`}
              label=""
              value={value}
              rows={3}
              onChange={(v) => setKey(key, v)}
            />
          )
        }
        return (
          <div key={key} className="field">
            <label htmlFor={id}>{label}</label>
            {control}
            {hint && <span className="muted small">{hint}</span>}
          </div>
        )
      })}
      <button className="link-button" onClick={() => setRaw(true)}>
        Edit as JSON
      </button>
    </div>
  )
}
