const test = require('node:test')
const assert = require('node:assert/strict')
const { harness, storage, user, tokens, reply, reject, settle } = require('./runtime.cjs')

function sockets() {
  const created = []
  global.WebSocket = class {
    static OPEN = 1
    static CONNECTING = 0
    readyState = 0
    constructor(url, protocols) { this.url = url; this.protocols = protocols; created.push(this) }
    close() { this.closed = true; this.readyState = 3 }
    send(data) { this.sent = data }
  }
  return created
}

test('socket authenticates with subprotocol and unmount closes pending connection', async () => {
  storage({ user, token: 'access', refreshToken: 'refresh' })
  const created = sockets(), h = harness()
  h.load('hooks/useWebSocket').useWebSocket({ url: 'ws://localhost/api/ws/practice/s1' })
  const cleanup = h.mount(); await settle()
  assert.deepEqual(created[0].protocols, ['salesagent', 'bearer.access'])
  cleanup.forEach(fn => fn())
  assert.equal(created[0].closed, true)
})

function timers(t) {
  let nextId = 0
  const queue = new Map(), delays = []
  const originalSet = global.setTimeout, originalClear = global.clearTimeout
  global.setTimeout = (callback, delay) => { const id = ++nextId; queue.set(id, callback); delays.push(delay); return id }
  global.clearTimeout = id => queue.delete(id)
  t.after(() => { global.setTimeout = originalSet; global.clearTimeout = originalClear })
  return { queue, delays, advance: async () => {
    const [id, callback] = queue.entries().next().value || []
    if (!callback) return false
    queue.delete(id); callback(); await settle(); return true
  } }
}
const callbacks = () => ({ onConnecting() {}, onConnected() {}, onDisconnected() {}, onMessage() {}, onError() {} })

test('transport close retries with bounded backoff and retrieves token dynamically', async t => {
  storage({ user, token: 'first' })
  const created = sockets(), clock = timers(t), h = harness()
  const connection = h.load('hooks/webSocketConnection').createWebSocketConnection('ws://localhost/s1', callbacks())
  t.after(() => connection.disconnect()); await settle()
  created[0].onclose({ code: 1011 })
  storage({ user, token: 'rotated' })
  await clock.advance()
  assert.deepEqual(created[1].protocols, ['salesagent', 'bearer.rotated'])
  for (let i = 1; i <= 5; i++) {
    created[i].onclose({ code: 1011 })
    await clock.advance()
  }
  assert.equal(created.length, 6)
  assert.deepEqual(clock.delays, [1000, 2000, 4000, 8000, 16000])
  assert.equal(clock.queue.size, 0)
})

for (const code of [1000, 1008, 4401, 4403]) {
  test(`server close ${code} stops without reconnecting`, async t => {
    storage({ user, token: 'access', refreshToken: 'refresh' })
    const created = sockets(), clock = timers(t), h = harness()
    let disconnected = 0
    const connection = h.load('hooks/webSocketConnection').createWebSocketConnection('ws://localhost/s1', {
      ...callbacks(), onDisconnected() { disconnected++ },
    })
    t.after(() => connection.disconnect()); await settle()
    created[0].onclose({ code })
    assert.equal(clock.queue.size, 0)
    assert.equal(disconnected, 1)
  })
}

test('intentional disconnect cancels scheduled retry and ignores queued callbacks', async t => {
  storage({ user, token: 'access' })
  const created = sockets(), clock = timers(t), h = harness()
  let connected = 0
  const connection = h.load('hooks/webSocketConnection').createWebSocketConnection('ws://localhost/s1', {
    ...callbacks(), onConnected() { connected++ },
  })
  await settle()
  const oldOpen = created[0].onopen, oldClose = created[0].onclose
  oldClose({ code: 1011 }); connection.disconnect(); oldOpen(); oldClose({ code: 1011 })
  assert.equal(connected, 0)
  assert.equal(clock.queue.size, 0)
  assert.equal(created.length, 1)
})

test('URL replacement cleans old socket and only delivers messages to current callbacks', async t => {
  storage({ user, token: 'access' })
  const created = sockets(), h = harness(), hook = h.load('hooks/useWebSocket').useWebSocket
  const received = []
  h.render(() => hook({ url: 'ws://localhost/old', onMessage: message => received.push(['old', message.content]) }))
  h.mount(); await settle()
  const staleMessage = created[0].onmessage, staleClose = created[0].onclose
  h.render(() => hook({ url: 'ws://localhost/new', onMessage: message => received.push(['new', message.content]) }))
  const cleanup = h.mount(); t.after(() => cleanup.forEach(fn => fn())); await settle()
  assert.equal(created[0].closed, true)
  assert.equal(created[1].url, 'ws://localhost/new')
  staleMessage({ data: JSON.stringify({ type: 'ai_message', content: 'stale' }) }); staleClose({ code: 1011 })
  h.render(() => hook({ url: 'ws://localhost/new', onMessage: message => received.push(['latest', message.content]) }))
  assert.equal(h.mount().length, 0)
  created[1].onmessage({ data: JSON.stringify({ type: 'ai_message', content: 'current' }) })
  assert.deepEqual(received, [['latest', 'current']])
  assert.equal(created.length, 2)
})

test('logout during preconnect renewal prevents socket creation and session resurrection', async t => {
  const expiredJwt = `e30.${Buffer.from(JSON.stringify({ exp: 1 })).toString('base64url')}.sig`
  storage({ user, token: expiredJwt, refreshToken: 'refresh' })
  const created = sockets(), h = harness(), session = h.load('api/session')
  let release
  h.client.defaults.adapter = async config => {
    await new Promise(resolve => { release = resolve })
    return reply(config, tokens)
  }
  const connection = h.load('hooks/webSocketConnection').createWebSocketConnection('ws://localhost/s1', callbacks())
  t.after(() => connection.disconnect()); await settle()
  session.clearSession(); release(); await settle()
  assert.equal(created.length, 0)
  assert.equal(localStorage.getItem('sales_agent_auth'), null)
})

test('ambiguous handshake rejection renews only once before retrying with the new token', async t => {
  storage({ user, token: 'access', refreshToken: 'refresh' })
  const created = sockets(), h = harness(), clock = timers(t)
  let refreshes = 0
  h.client.defaults.adapter = async config => { refreshes++; return reply(config, tokens) }
  const connection = h.load('hooks/webSocketConnection').createWebSocketConnection('ws://localhost/s1', callbacks())
  t.after(() => connection.disconnect()); await settle()
  created[0].onclose({ code: 1006 }); await settle(); await clock.advance()
  assert.deepEqual(created[1].protocols, ['salesagent', 'bearer.new-access'])
  created[1].onclose({ code: 1006 }); await settle(); await clock.advance()
  assert.equal(refreshes, 1)
  assert.equal(created.length, 3)
})

test('temporary preconnect renewal failure keeps session and retries after backoff', async t => {
  const expiredJwt = `e30.${Buffer.from(JSON.stringify({ exp: 1 })).toString('base64url')}.sig`
  storage({ user, token: expiredJwt, refreshToken: 'refresh' })
  const created = sockets(), h = harness(), clock = timers(t)
  let offline = true
  h.client.defaults.adapter = async config => {
    if (offline) reject(config, 503)
    return reply(config, tokens)
  }
  const connection = h.load('hooks/webSocketConnection').createWebSocketConnection('ws://localhost/s1', callbacks())
  t.after(() => connection.disconnect()); await settle()
  assert.equal(created.length, 0)
  assert.ok(localStorage.getItem('sales_agent_auth'))
  offline = false; await clock.advance()
  assert.deepEqual(created[0].protocols, ['salesagent', 'bearer.new-access'])
})


test('established socket renews an expired JWT before sending the next message', async t => {
  const initialJwt = `e30.${Buffer.from(JSON.stringify({ exp: Date.now()/1000+300 })).toString('base64url')}.sig`
  storage({ user, token: initialJwt, refreshToken: 'refresh' })
  const created = sockets(), h = harness(), sent = []
  let renewals = 0
  h.client.defaults.adapter = async config => { renewals++; return reply(config, tokens) }
  const connection = h.load('hooks/webSocketConnection').createWebSocketConnection('ws://localhost/s1', callbacks())
  t.after(() => connection.disconnect()); await settle()
  created[0].readyState = WebSocket.OPEN; created[0].onopen(); created[0].send = data => sent.push(data)
  const expiredJwt = `e30.${Buffer.from(JSON.stringify({ exp: 1 })).toString('base64url')}.sig`
  storage({ user, token: expiredJwt, refreshToken: 'refresh' })
  connection.send(JSON.stringify({ type: 'user_message', content: 'hello' })); await settle()
  assert.equal(renewals, 1)
  assert.deepEqual(sent.map(value => JSON.parse(value)), [
    { type: 'auth_refresh', access_token: 'new-access' }, { type: 'user_message', content: 'hello' },
  ])
})
