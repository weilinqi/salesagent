const test = require('node:test')
const assert = require('node:assert/strict')
const { harness, storage, user, tokens, reply, reject, settle } = require('./runtime.cjs')

function sessionHarness(t, initial = { user, token: 'expired', refreshToken: 'refresh' }) {
  storage(initial)
  const h = harness(), session = h.load('api/session')
  t.after(session.installAuthInterceptors())
  return { ...h, session }
}

test('expired access token refreshes once and replays profile request', async () => {
  storage({ user, token: 'expired', refreshToken: 'refresh' })
  const h = harness(), calls = []
  h.client.defaults.adapter = async config => {
    calls.push(config.url)
    if (config.url.endsWith('/refresh')) { assert.deepEqual(JSON.parse(config.data), { refresh_token: 'refresh' }); return reply(config, tokens) }
    if (config.headers.Authorization === 'Bearer expired') reject(config, 401)
    return reply(config, user)
  }
  h.load('contexts/AuthContext').AuthProvider({ children: null }); const cleanup = h.mount()
  await settle()
  assert.deepEqual(calls, ['/api/v1/auth/me', '/api/v1/auth/refresh', '/api/v1/auth/me'])
  assert.equal(JSON.parse(localStorage.getItem('sales_agent_auth')).refreshToken, 'new-refresh')
  cleanup.forEach(fn => fn())
})

test('parallel unauthorized requests share one renewal and use the rotated access token', async t => {
  const { client } = sessionHarness(t)
  let refreshes = 0, release
  client.defaults.adapter = async config => {
    if (config.url.endsWith('/refresh')) {
      refreshes++
      await new Promise(resolve => { release = resolve })
      return reply(config, tokens)
    }
    if (config.headers.Authorization === 'Bearer expired') reject(config, 401)
    assert.equal(config.headers.Authorization, 'Bearer new-access')
    return reply(config, { ok: true })
  }
  const requests = [client.get('/api/v1/one'), client.get('/api/v1/two')]
  await settle(); assert.equal(refreshes, 1); release()
  assert.deepEqual((await Promise.all(requests)).map(response => response.data), [{ ok: true }, { ok: true }])
})

test('definitively invalid refreshed access token retries original request once and signs out', async t => {
  const { client } = sessionHarness(t)
  let protectedCalls = 0, refreshes = 0
  client.defaults.adapter = async config => {
    if (config.url.endsWith('/refresh')) { refreshes++; return reply(config, tokens) }
    protectedCalls++; reject(config, 401)
  }
  await assert.rejects(client.get('/api/v1/one'))
  assert.equal(protectedCalls, 2)
  assert.equal(refreshes, 1)
  assert.equal(localStorage.getItem('sales_agent_auth'), null)
})

for (const status of [401, 403, 503]) {
  test(`refresh ${status} ${status === 503 ? 'preserves' : 'clears'} session`, async t => {
    const { client } = sessionHarness(t)
    client.defaults.adapter = async config => reject(config, config.url.endsWith('/refresh') ? status : 401)
    await assert.rejects(client.get('/api/v1/one'))
    assert.equal(!!localStorage.getItem('sales_agent_auth'), status === 503)
  })
}

test('network failure during renewal preserves session for a successful manual retry', async t => {
  const { client } = sessionHarness(t)
  let offline = true
  client.defaults.adapter = async config => {
    if (config.url.endsWith('/refresh')) {
      if (offline) throw new Error('network offline')
      return reply(config, tokens)
    }
    if (config.headers.Authorization === 'Bearer expired') reject(config, 401)
    return reply(config, { ok: true })
  }
  await assert.rejects(client.get('/api/v1/one'))
  assert.ok(localStorage.getItem('sales_agent_auth'))
  offline = false
  assert.deepEqual((await client.get('/api/v1/one')).data, { ok: true })
})

test('logout and account switch discard late renewal instead of overwriting the new user', async t => {
  const { client, session } = sessionHarness(t)
  let release
  client.defaults.adapter = async config => {
    if (config.url.endsWith('/refresh')) {
      await new Promise(resolve => { release = resolve })
      return reply(config, tokens)
    }
    reject(config, 401)
  }
  const request = client.get('/api/v1/one')
  const rejected = assert.rejects(request, { name: 'SessionChangedError' })
  await settle()
  session.clearSession()
  session.saveSession({ ...tokens, user: { ...user, id: 'u2' }, access_token: 'account-two' })
  release(); await rejected
  assert.equal(JSON.parse(localStorage.getItem('sales_agent_auth')).token, 'account-two')
})

test('late profile response after logout cannot restore provider state', async () => {
  storage({ user, token: 'valid', refreshToken: 'refresh' })
  const h = harness(); let release
  h.client.defaults.adapter = async config => {
    if (config.url.endsWith('/me')) await new Promise(resolve => { release = resolve })
    return reply(config, user)
  }
  const provider = h.load('contexts/AuthContext').AuthProvider({ children: null })
  const cleanup = h.mount(); await settle()
  await provider.props.value.logout()
  release(); await settle()
  assert.equal(h.states[0].isAuthenticated, false)
  assert.equal(localStorage.getItem('sales_agent_auth'), null)
  cleanup.forEach(fn => fn())
})

test('auth failures never refresh or erase another session, and external requests do not receive its JWT', async t => {
  const { client } = sessionHarness(t)
  const calls = []
  client.defaults.adapter = async config => {
    calls.push(config.url)
    assert.equal(config.headers.Authorization, undefined)
    reject(config, 401)
  }
  for (const endpoint of ['login', 'register', 'refresh', 'logout']) await assert.rejects(client.post(`/api/v1/auth/${endpoint}`, {}))
  await assert.rejects(client.get('https://example.invalid/anything'))
  assert.equal(calls.length, 5)
  assert.ok(localStorage.getItem('sales_agent_auth'))
})

test('legacy access-only sessions are usable until the server rejects them', async t => {
  const { client } = sessionHarness(t, { user, token: 'legacy' })
  client.defaults.adapter = async config => {
    assert.equal(config.headers.Authorization, 'Bearer legacy')
    return reply(config, user)
  }
  await client.get('/api/v1/auth/me')
  client.defaults.adapter = async config => reject(config, 401)
  await assert.rejects(client.get('/api/v1/auth/me'))
  assert.equal(localStorage.getItem('sales_agent_auth'), null)
})

test('provider cleanup ejects both interceptors so later requests keep caller headers', async () => {
  storage()
  const h = harness()
  h.load('contexts/AuthContext').AuthProvider({ children: null }); h.mount().forEach(fn => fn())
  storage({ user, token: 'stored' })
  h.client.defaults.adapter = async config => {
    assert.equal(config.headers.Authorization, 'Bearer explicit')
    return reply(config, {})
  }
  await h.client.get('/api/v1/one', { headers: { Authorization: 'Bearer explicit' } })
})

test('temporary profile failure preserves stored session and offers retry', async () => {
  storage({ user, token: 'valid', refreshToken: 'refresh' })
  const h = harness()
  h.client.defaults.adapter = async config => reject(config, 503)
  h.load('contexts/AuthContext').AuthProvider({ children: null }); const cleanup = h.mount()
  await settle()
  assert.ok(localStorage.getItem('sales_agent_auth'))
  assert.equal(h.states[0].isAuthenticated, true)
  assert.ok(h.states[0].sessionError)
  cleanup.forEach(fn => fn())
})


test('another tab logout prevents late refresh from restoring shared storage', async () => {
  storage({ user, token: 'access', refreshToken: 'refresh' })
  const h = harness(), session = h.load('api/session')
  let release
  h.client.defaults.adapter = async config => { await new Promise(resolve => { release = resolve }); return reply(config, tokens) }
  const pending = session.refreshAccessToken(); await settle()
  localStorage.removeItem('sales_agent_auth') // Logout in a different tab, no module-version change.
  release(); await assert.rejects(pending)
  assert.equal(localStorage.getItem('sales_agent_auth'), null)
})

test('another tab account switch cannot be overwritten by an old refresh response', async () => {
  storage({ user, token: 'access', refreshToken: 'refresh' })
  const h = harness(), session = h.load('api/session')
  let release
  h.client.defaults.adapter = async config => { await new Promise(resolve => { release = resolve }); return reply(config, tokens) }
  const pending = session.refreshAccessToken(); await settle()
  const other = { ...user, id: 'other-account' }
  storage({ user: other, token: 'other-access', refreshToken: 'other-refresh' })
  release(); await assert.rejects(pending)
  assert.equal(JSON.parse(localStorage.getItem('sales_agent_auth')).user.id, 'other-account')
})
