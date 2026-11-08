import { ensureAccessToken, getSessionVersion, isCurrentSession, readSession, refreshAccessToken, subscribeSession } from '../api/session'

interface ConnectionCallbacks {
  onConnecting: () => void
  onConnected: () => void
  onDisconnected: () => void
  onMessage: (event: MessageEvent) => void
  onError: (event: Event) => void
}

/** Own one URL's sockets and timers; no callback from a replaced socket can act on its successor. */
export function createWebSocketConnection(url: string, callbacks: ConnectionCallbacks) {
  const expected = getSessionVersion()
  let socket: WebSocket | null = null
  let socketToken: string | null = null
  let sends: Promise<void> = Promise.resolve()
  let stopped = false
  let attempts = 0
  let handshakeRenewed = false
  let retryTimer: ReturnType<typeof setTimeout> | undefined
  let stableTimer: ReturnType<typeof setTimeout> | undefined
  let handshakeTimer: ReturnType<typeof setTimeout> | undefined
  const current = () => !stopped && isCurrentSession(expected)
  const failure = (message: string) => Object.assign(new Event('error'), { message })
  const clearTimers = () => { clearTimeout(retryTimer); clearTimeout(stableTimer); clearTimeout(handshakeTimer) }
  const disconnect = (message?: string) => {
    if (stopped) return
    stopped = true
    clearTimers()
    unsubscribe()
    if (socket) {
      socket.onopen = socket.onmessage = socket.onclose = socket.onerror = null
      socket.close(1000, 'Client disconnect')
      socket = null
    }
    callbacks.onDisconnected()
    if (message) callbacks.onError(failure(message))
  }
  const updateSocketToken = (token: string) => {
    if (socket?.readyState === WebSocket.OPEN && token !== socketToken) {
      socket.send(JSON.stringify({ type: 'auth_refresh', access_token: token }))
      socketToken = token
    }
  }
  const unsubscribe = subscribeSession(() => {
    if (!isCurrentSession(expected)) disconnect()
    else {
      const token = readSession()?.token
      if (token) updateSocketToken(token)
    }
  })
  const retry = () => {
    if (!current()) { disconnect(); return }
    if (attempts >= 5) { disconnect('无法连接对练服务器，请检查后端端口、WebSocket 代理或重新登录后重试。'); return }
    const delay = Math.min(1000 * 2 ** attempts++, 16000)
    retryTimer = setTimeout(() => { retryTimer = undefined; void connect() }, delay)
  }
  const connect = async () => {
    if (!current() || socket) return
    callbacks.onConnecting()
    try {
      const token = await ensureAccessToken()
      if (!current()) return
      if (!token) { disconnect('登录已过期，请重新登录后连接对练。'); return }
      const ws = new WebSocket(url, ['salesagent', `bearer.${token}`])
      socket = ws
      socketToken = token
      ws.binaryType = 'arraybuffer'
      let opened = false
      const ownsSocket = () => current() && socket === ws
      handshakeTimer = setTimeout(() => {
        if (!ownsSocket()) return
        socket = null
        ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null
        ws.close()
        callbacks.onDisconnected()
        callbacks.onError(failure('连接对练服务器超时，正在尝试重新连接。'))
        retry()
      }, 10000)
      ws.onopen = () => {
        if (!ownsSocket()) return
        clearTimeout(handshakeTimer)
        opened = true
        callbacks.onConnected()
        if (ownsSocket()) stableTimer = setTimeout(() => { if (ownsSocket()) attempts = 0 }, 10000)
      }
      ws.onmessage = event => { if (ownsSocket()) callbacks.onMessage(event) }
      ws.onerror = event => { if (ownsSocket()) callbacks.onError(event) }
      ws.onclose = event => {
        if (!ownsSocket()) return
        clearTimeout(stableTimer)
        clearTimeout(handshakeTimer)
        socket = null
        if ([1000, 1008, 4401, 4403].includes(event.code)) {
          disconnect(event.code === 1000 ? '对练连接已关闭，可点击重新连接。' : '服务器拒绝连接，请检查登录状态、会话权限或访问地址。')
          return
        }
        callbacks.onDisconnected()
        // Browsers conceal an HTTP handshake rejection as 1006. Try renewal once;
        // subsequent transport failures use the same bounded backoff as disconnects.
        if (!opened && event.code === 1006 && !handshakeRenewed && readSession()?.refreshToken) {
          handshakeRenewed = true
          void refreshAccessToken().then(() => { if (current()) retry() }).catch(() => {
            if (current()) { callbacks.onError(new Event('error')); retry() }
          })
        } else retry()
      }
    } catch {
      if (current()) { callbacks.onDisconnected(); callbacks.onError(new Event('error')); retry() }
    }
  }
  void connect()
  return {
    disconnect,
    send(data: string | Uint8Array) {
      const target = socket
      sends = sends.then(async () => {
        if (!current() || target !== socket || target?.readyState !== WebSocket.OPEN) return
        const token = await ensureAccessToken()
        if (!current() || target !== socket || target.readyState !== WebSocket.OPEN || !token) return
        updateSocketToken(token)
        target.send(data)
      }).catch(() => { if (current()) callbacks.onError(new Event('error')) })
    },
  }
}
