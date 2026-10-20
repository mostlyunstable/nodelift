import { defineConfig } from '@playwright/test'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const API = 8765
const WEB = 5199
// A throwaway data folder per run: end-to-end tests never touch your real workflows or repositories.
const data = mkdtempSync(join(tmpdir(), 'nodecraft-e2e-'))

export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: { baseURL: `http://127.0.0.1:${WEB}`, trace: 'retain-on-failure' },
  webServer: [
    {
      command: 'uv run python -m app',
      cwd: '../../backend',
      url: `http://127.0.0.1:${API}/api/v1/health`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        NODECRAFT_DATA_DIR: data,
        NODECRAFT_PORT: String(API),
        NODECRAFT_SECRET_BACKEND: 'memory',
        NODECRAFT_ALLOWED_ORIGINS: `http://127.0.0.1:${WEB},http://localhost:${WEB}`,
      },
    },
    {
      command: `pnpm exec vite --host 127.0.0.1 --port ${WEB} --strictPort`,
      url: `http://127.0.0.1:${WEB}`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: { NODECRAFT_API_TARGET: `http://127.0.0.1:${API}`, NODECRAFT_WEB_PORT: String(WEB) },
    },
  ],
})
