/** One backend target for HTTP and WebSocket traffic; no secrets enter client code. */
export function backendProxy(port = '8002') {
  if (!/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535) {
    throw new Error('Backend PORT must be an integer between 1 and 65535')
  }
  return {
    '/api': { target: `http://127.0.0.1:${Number(port)}`, changeOrigin: true },
    '/ws': { target: `ws://127.0.0.1:${Number(port)}`, ws: true },
  }
}
