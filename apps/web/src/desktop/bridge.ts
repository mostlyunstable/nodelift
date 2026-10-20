import { setApiConfig } from '../api/config'

export interface BackendInfo {
  baseUrl: string
  token: string
}

export interface StartupFailure {
  message: string
  logTail: string[]
  logPath: string | null
}

/** What the desktop shell offers the UI. The real implementation talks to Tauri; tests pass a fake. */
export interface DesktopBridge {
  waitForBackend(): Promise<BackendInfo>
  restartBackend(): Promise<void>
  revealLogs(): Promise<void>
  onBackendExit(cb: (reason: string) => void): Promise<() => void>
}

export const isDesktop = (): boolean => typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window

export function tauriBridge(): DesktopBridge {
  return {
    async waitForBackend() {
      const { invoke } = await import('@tauri-apps/api/core')
      return invoke<BackendInfo>('wait_for_backend')
    },
    async restartBackend() {
      const { invoke } = await import('@tauri-apps/api/core')
      await invoke('restart_backend')
    },
    async revealLogs() {
      const { invoke } = await import('@tauri-apps/api/core')
      await invoke('reveal_logs')
    },
    async onBackendExit(cb) {
      const { listen } = await import('@tauri-apps/api/event')
      return listen<string>('backend-exited', (e) => cb(e.payload))
    },
  }
}

export function applyBackendInfo(info: BackendInfo): void {
  setApiConfig({ baseUrl: info.baseUrl, token: info.token })
}
