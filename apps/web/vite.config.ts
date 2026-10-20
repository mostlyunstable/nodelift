/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { execSync } from 'node:child_process'
import { defineConfig } from 'vite'

// When the backend runs with NODECRAFT_API_TOKEN, the dev proxy attaches it so the browser never holds it.
const token = process.env.NODECRAFT_API_TOKEN
// End-to-end tests run their own backend and dev server on other ports.
const apiTarget = process.env.NODECRAFT_API_TARGET ?? 'http://127.0.0.1:8000'

// Which build is this? Shown in Diagnostics and as the tooltip on the app name, so an old build is easy to spot.
const gitSha = (() => {
  try {
    return execSync('git rev-parse --short HEAD', { stdio: ['ignore', 'pipe', 'ignore'] })
      .toString()
      .trim()
  } catch {
    return 'unknown'
  }
})()
const buildId = `${gitSha} · ${new Date().toISOString().slice(0, 16).replace('T', ' ')} UTC`

export default defineConfig({
  define: { __BUILD_ID__: JSON.stringify(buildId) },
  plugins: [react()],
  build: { chunkSizeWarningLimit: 5000 }, // Monaco is bundled for offline use; this is a local app
  server: {
    port: Number(process.env.NODECRAFT_WEB_PORT ?? 5173),
    proxy: {
      '/api': {
        target: apiTarget,
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    globals: true,
    exclude: ['e2e/**', 'node_modules/**'], // Playwright specs run with `pnpm e2e`
  },
})
