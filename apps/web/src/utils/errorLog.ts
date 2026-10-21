/** Errors the interface hit this session, kept in memory so "Copy diagnostics" can include them. Nothing is sent anywhere. */
const entries: string[] = []

export function recordError(where: string, err: unknown): void {
  const text = err instanceof Error ? `${err.name}: ${err.message}\n${err.stack ?? ''}` : String(err)
  entries.push(`[${new Date().toISOString()}] ${where}: ${text.slice(0, 1500)}`)
  if (entries.length > 20) entries.shift()
}

export const recordedErrors = (): string[] => [...entries]

export function watchErrors(): void {
  window.addEventListener('error', (e) => recordError('error', e.error ?? e.message))
  window.addEventListener('unhandledrejection', (e) => recordError('unhandled rejection', e.reason))
}

/** Offers `text` as a download, for when a customer is asked to send a report. */
export function saveTextFile(name: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain' }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}
