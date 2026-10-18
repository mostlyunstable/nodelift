import Editor from '@monaco-editor/react'
import type { FlowNode } from '../canvas/mapper'
import { JsonField } from '../editor/JsonField'
import { useStore } from '../state/store'

const METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD']

function CodeConfig({ node }: { node: FlowNode }) {
  const { updateConfig } = useStore()
  return (
    <>
      <div className="field">
        Python — define <code>main(input_data)</code>
      </div>
      <div className="editor">
        <Editor
          height="240px"
          language="python"
          theme="vs-dark"
          value={String(node.data.config.source ?? '')}
          onChange={(v) => updateConfig(node.id, { source: v ?? '' })}
          options={{ minimap: { enabled: false }, fontSize: 13, scrollBeyondLastLine: false }}
        />
      </div>
    </>
  )
}

function TransformConfig({ node }: { node: FlowNode }) {
  const { updateConfig } = useStore()
  return (
    <>
      <JsonField
        key={node.id}
        label='Mapping: output key → "$.path" or {"literal": value}'
        value={node.data.config.mapping}
        rows={8}
        onChange={(v) => updateConfig(node.id, { mapping: v })}
      />
      <label className="check">
        <input
          type="checkbox"
          checked={node.data.config.strict === true}
          onChange={(e) => updateConfig(node.id, { strict: e.target.checked })}
        />{' '}
        Fail when a path is missing
      </label>
    </>
  )
}

function HttpConfig({ node }: { node: FlowNode }) {
  const { updateConfig } = useStore()
  const c = node.data.config
  return (
    <>
      <label className="field">
        URL
        <input value={String(c.url ?? '')} onChange={(e) => updateConfig(node.id, { url: e.target.value })} />
      </label>
      <label className="field">
        Method
        <select
          value={String(c.method ?? 'GET')}
          onChange={(e) => updateConfig(node.id, { method: e.target.value })}
        >
          {METHODS.map((m) => (
            <option key={m}>{m}</option>
          ))}
        </select>
      </label>
      <JsonField
        key={`${node.id}-h`}
        label="Headers (JSON object)"
        value={c.headers ?? {}}
        onChange={(v) => updateConfig(node.id, { headers: v })}
      />
      <JsonField
        key={`${node.id}-b`}
        label="Body (JSON, optional)"
        value={c.body}
        onChange={(v) => updateConfig(node.id, { body: v })}
      />
      <label className="check">
        <input
          type="checkbox"
          checked={c.send_input_as_body === true}
          onChange={(e) => updateConfig(node.id, { send_input_as_body: e.target.checked })}
        />{' '}
        Send the node input as the body
      </label>
      <div className="muted">
        Private, loopback and cloud-metadata addresses are blocked. Redirects are not followed. Don't put secrets in
        headers yet — workflows are stored unencrypted.
      </div>
    </>
  )
}

/** Plugin or unknown node types get a raw JSON editor so they stay usable without UI work. */
function RawConfig({ node }: { node: FlowNode }) {
  const { updateData } = useStore()
  return (
    <JsonField
      key={node.id}
      label="Config (JSON)"
      value={node.data.config}
      rows={10}
      onChange={(v) => updateData(node.id, { config: (v as Record<string, unknown>) ?? {} })}
    />
  )
}

export function ConfigEditor({ node }: { node: FlowNode }) {
  switch (node.data.nodeType) {
    case 'code.python':
      return <CodeConfig node={node} />
    case 'transform.json':
      return <TransformConfig node={node} />
    case 'http.request':
      return <HttpConfig node={node} />
    default:
      return <RawConfig node={node} />
  }
}
