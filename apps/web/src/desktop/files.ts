import { isDesktop } from './bridge'

/**
 * Save text to a file the user chooses. The desktop app uses the native save dialog (a webview cannot
 * download blobs); the browser uses a normal download. Returns false if the user cancelled.
 */
export async function saveTextFile(defaultName: string, text: string): Promise<boolean> {
  if (isDesktop()) {
    const { save } = await import('@tauri-apps/plugin-dialog')
    const { writeTextFile } = await import('@tauri-apps/plugin-fs')
    const path = await save({ defaultPath: defaultName, filters: [{ name: 'Nodecraft workflow', extensions: ['json'] }] })
    if (!path) return false
    await writeTextFile(path, text)
    return true
  }
  const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }))
  const link = document.createElement('a')
  link.href = url
  link.download = defaultName
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  return true
}

export const fileSlug = (name: string): string =>
  name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60) || 'workflow'
