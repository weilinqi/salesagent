// Local-only smoke check: Node 22.18+; backend port 8002 must be free.
import assert from 'node:assert/strict'
import http from 'node:http'
import { createHash } from 'node:crypto'
import { createServer } from 'vite'
import config from './vite.config.ts'

const upstream = http.createServer((req, res) => {
  res.setHeader('Content-Type', 'application/json')
  res.end(JSON.stringify({ path: req.url }))
})
let upgradedPath
upstream.on('upgrade', (req, socket) => {
  upgradedPath = req.url
  const accept = createHash('sha1')
    .update(req.headers['sec-websocket-key'] + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11')
    .digest('base64')
  socket.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ' + accept + '\r\n\r\n')
  // Send an empty, valid WebSocket close frame after the successful handshake.
  socket.end(Buffer.from([0x88, 0x00]))
})
let vite
try {
  await new Promise((resolve, reject) => {
    upstream.once('error', reject)
    upstream.listen(8002, '127.0.0.1', resolve)
  })
  vite = await createServer({
    ...config,
    configFile: false,
    server: { ...config.server, host: '127.0.0.1', port: 0 },
    optimizeDeps: { noDiscovery: true, include: [] },
    logLevel: 'error',
  })
  await vite.listen()
  const port = vite.httpServer.address().port
  const response = await fetch(`http://127.0.0.1:${port}/api/v1/proxy-check`)
  assert.equal(response.status, 200)
  assert.deepEqual(await response.json(), { path: '/api/v1/proxy-check' })
  await new Promise((resolve, reject) => {
    const ws = new WebSocket(`ws://127.0.0.1:${port}/ws/practice/proxy-check`)
    const timer = setTimeout(() => { ws.close(); reject(new Error('WebSocket proxy timed out')) }, 5000)
    ws.addEventListener('open', () => { clearTimeout(timer); resolve() })
    ws.addEventListener('error', () => { clearTimeout(timer); reject(new Error('WebSocket proxy failed')) })
  })
  assert.equal(upgradedPath, '/ws/practice/proxy-check')
  console.log('PASS: HTTP /api and WebSocket /ws proxy reach backend:8002 with paths preserved.')
} finally {
  if (vite) await vite.close()
  upstream.closeAllConnections()
  await new Promise(resolve => upstream.close(resolve))
}
