import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'node:path'
import { backendProxy } from './config/backendProxy'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  // Read only PORT from the backend environment; do not expose API credentials.
  const backend = loadEnv(mode, resolve(__dirname, '../backend'), 'PORT')
  const proxy = backendProxy(backend.PORT || '8002')
  return {
    plugins: [react()],
    server: { port: 5173, proxy },
    preview: { proxy },
  }
})
