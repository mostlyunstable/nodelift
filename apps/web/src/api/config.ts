/** Where the backend lives and how to authenticate. Browser dev uses the Vite proxy: same origin, no token. */
export interface ApiConfig {
  baseUrl: string // '' = same origin
  token: string | null
}

let config: ApiConfig = { baseUrl: '', token: null }

export const getApiConfig = (): ApiConfig => config
export const setApiConfig = (next: ApiConfig): void => {
  config = { baseUrl: next.baseUrl.replace(/\/$/, ''), token: next.token }
}

export function apiUrl(path: string): string {
  return `${config.baseUrl}/api/v1${path}`
}

export function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return config.token ? { ...extra, Authorization: `Bearer ${config.token}` } : extra
}
