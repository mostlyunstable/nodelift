export function Json({ value }: { value: unknown }) {
  const text = value === undefined ? '' : JSON.stringify(value, null, 2)
  return <pre className="json">{text === '' || text === undefined ? 'null' : text}</pre>
}
