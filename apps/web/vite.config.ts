/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// When the backend runs with NODECRAFT_API_TOKEN, the dev proxy attaches it so the browser never holds it.
const token = process.env.NODECRAFT_API_TOKEN

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      },
    },
  },
  test: { environment: 'jsdom', setupFiles: ['./src/test-setup.ts'], globals: true },
})
