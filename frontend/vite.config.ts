import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'node:path'
import { backendProxy } from './config/backendProxy'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  // CLI --port can override backend/.env. Select the actual running backend
  // explicitly instead of treating that file's PORT as a live service address.
  const frontend = loadEnv(mode, resolve(__dirname), 'SALESAGENT_')
  const proxy = backendProxy(frontend.SALESAGENT_BACKEND_PORT || '8002')
  return {
    plugins: [react()],
    server: { port: 5173, proxy },
    preview: { proxy },
  }
})
