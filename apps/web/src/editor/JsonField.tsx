import { useState } from 'react'

interface Props {
  label: string
  value: unknown
  onChange: (value: unknown) => void
  rows?: number
}

/** Edits a JSON value as text; commits only when the text parses, so typing never loses work. */
export function JsonField({ label, value, onChange, rows = 4 }: Props) {
  const [text, setText] = useState(() => (value === undefined ? '' : JSON.stringify(value, null, 2)))
  const [error, setError] = useState<string | null>(null)
  return (
    <label className="field">
      {label}
      <textarea
        rows={rows}
        value={text}
        onChange={(e) => {
          setText(e.target.value)
          try {
            onChange(e.target.value.trim() === '' ? undefined : JSON.parse(e.target.value))
            setError(null)
          } catch (err) {
            setError((err as Error).message)
          }
        }}
      />
      {error && <span className="field-error">Invalid JSON: {error}</span>}
    </label>
  )
}
