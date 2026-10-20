export function Json({ value }: { value: unknown }) {
  const text = value === undefined ? '' : JSON.stringify(value, null, 2)
  return (
    <pre className="json" role="region" tabIndex={0} aria-label="Data">
      {text === '' || text === undefined ? 'null' : text}
    </pre>
  )
}
