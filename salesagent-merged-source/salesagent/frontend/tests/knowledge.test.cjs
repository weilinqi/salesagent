const test = require('node:test')
const assert = require('node:assert/strict')
const { harness, reply, settle } = require('./runtime.cjs')

function nodes(tree) {
  if (tree == null || typeof tree !== 'object') return []
  if (Array.isArray(tree)) return tree.flatMap(nodes)
  return [tree, ...nodes(tree.props?.children)]
}
function text(tree) {
  if (tree == null || typeof tree === 'boolean') return ''
  if (typeof tree !== 'object') return String(tree)
  if (Array.isArray(tree)) return tree.map(text).join('')
  return text(tree.props?.children)
}
function pageHarness() {
  const h = harness(), page = h.load('pages/Knowledge/KnowledgeBasePage').default
  const render = () => h.render(page)
  const open = async () => {
    const initial = render(); h.mount()
    nodes(initial).find(node => node.type === 'button' && text(node) === '文档管理').props.onClick()
    render(); const cleanup = h.mount(); await settle()
    return cleanup
  }
  return { ...h, render, open }
}
const queued = { id: 'd1', name: 'one.pdf', category: 'spin', status: 'queued', chunk_count: 0, error: null }
const stats = { total_documents: 1, total_chunks: 0, documents_by_category: { spin: 1 }, chunks_by_source: {} }

test('document UI renders failed ingestion with server error instead of pending', async t => {
  const h = pageHarness()
  h.client.defaults.adapter = async config => reply(config, config.url.endsWith('/documents') ? [{ ...queued, status: 'failed', error: 'PDF is encrypted' }] : stats)
  const cleanup = await h.open(); t.after(() => cleanup.forEach(fn => fn()))
  const visible = text(h.render())
  assert.match(visible, /失败/)
  assert.match(visible, /PDF is encrypted/)
})

test('queued ingestion feedback never claims completion and retains submission errors', async t => {
  const h = pageHarness(), alerts = [], previousAlert = global.alert
  global.alert = message => alerts.push(message); t.after(() => { global.alert = previousAlert })
  h.client.defaults.adapter = async config => {
    if (config.url.endsWith('/ingest-all')) return reply(config, {
      total: 2, results: [{ file: 'one.pdf', status: 'queued', document_id: 'd1', chunks: 0 }, { file: 'bad.pdf', status: 'failed', error: 'Invalid PDF document' }],
    })
    return reply(config, config.url.endsWith('/documents') ? [] : stats)
  }
  const cleanup = await h.open(); t.after(() => cleanup.forEach(fn => fn()))
  const syncButton = nodes(h.render()).find(node => node.type === 'button' && text(node).includes('同步原始数据'))
  await syncButton.props.onClick(); await settle()
  const feedback = text(h.render()) + alerts.join('')
  assert.match(feedback, /队列/)
  assert.match(feedback, /Invalid PDF document/)
  assert.doesNotMatch(feedback, /更新完成/)
})

function fakeClock(t) {
  const queue = new Map(), delays = []
  let nextId = 0
  const originalSet = global.setTimeout, originalClear = global.clearTimeout
  global.setTimeout = (callback, delay) => { const id = ++nextId; queue.set(id, callback); delays.push(delay); return id }
  global.clearTimeout = id => queue.delete(id)
  t.after(() => { global.setTimeout = originalSet; global.clearTimeout = originalClear })
  return { queue, delays, tick: async () => {
    const [id, callback] = queue.entries().next().value || []
    if (!callback) return false
    queue.delete(id); callback(); await settle(); return true
  } }
}

function monitorHarness(t) {
  const h = harness(), snapshots = []
  const monitor = h.load('api/knowledge').createKnowledgeMonitor(state => snapshots.push(state))
  t.after(() => monitor.dispose())
  return { ...h, monitor, snapshots, latest: () => snapshots.at(-1) }
}

test('queued jobs are polled through processing to completion and polling then stops', async t => {
  const clock = fakeClock(t), h = monitorHarness(t)
  let documentRequests = 0
  h.client.defaults.adapter = async config => {
    if (config.url.endsWith('/documents')) {
      const status = ['queued', 'processing', 'completed'][documentRequests++]
      return reply(config, [{ ...queued, status, chunk_count: status === 'completed' ? 8 : 0 }])
    }
    return reply(config, stats)
  }
  await h.monitor.refresh()
  assert.equal(h.latest().documents[0].status, 'queued')
  await clock.tick(); assert.equal(h.latest().documents[0].status, 'processing')
  await clock.tick(); assert.equal(h.latest().documents[0].chunk_count, 8)
  assert.equal(clock.queue.size, 0)
  assert.equal(documentRequests, 3)
})

test('bounded polling pauses for a long-running job and manual refresh resumes it', async t => {
  const clock = fakeClock(t), h = monitorHarness(t)
  let documentRequests = 0
  h.client.defaults.adapter = async config => {
    if (config.url.endsWith('/documents')) { documentRequests++; return reply(config, [queued]) }
    return reply(config, stats)
  }
  await h.monitor.refresh()
  for (let i = 0; i < 70 && await clock.tick(); i++) { /* Drain the bounded poll run. */ }
  assert.equal(documentRequests, 61)
  assert.equal(clock.queue.size, 0)
  assert.equal(h.latest().pollingPaused, true)
  assert.ok(clock.delays.every(delay => delay === 2000))
  await h.monitor.refresh()
  assert.equal(documentRequests, 62)
  assert.equal(h.latest().pollingPaused, false)
  assert.equal(clock.queue.size, 1)
})

test('offline poll retains last known jobs, pauses timers, and manual retry recovers', async t => {
  const clock = fakeClock(t), h = monitorHarness(t)
  let offline = false
  h.client.defaults.adapter = async config => {
    if (offline) throw new Error('Network unavailable')
    return reply(config, config.url.endsWith('/documents') ? [queued] : stats)
  }
  await h.monitor.refresh(); offline = true; await clock.tick()
  assert.equal(h.latest().documents[0].id, 'd1')
  assert.match(h.latest().loadError, /Network unavailable/)
  assert.equal(h.latest().pollingPaused, true)
  assert.equal(clock.queue.size, 0)
  offline = false; await h.monitor.refresh()
  assert.equal(h.latest().loadError, null)
  assert.equal(clock.queue.size, 1)
})

test('monitor disposal aborts pending requests and never publishes their late completion', async t => {
  const h = monitorHarness(t), signals = [], releases = []
  h.client.defaults.adapter = async config => {
    signals.push(config.signal)
    await new Promise(resolve => releases.push(resolve))
    return reply(config, config.url.endsWith('/documents') ? [queued] : stats)
  }
  const pending = h.monitor.refresh(); await settle()
  h.monitor.dispose()
  const count = h.snapshots.length
  assert.ok(signals.every(signal => signal.aborted))
  releases.forEach(release => release()); await pending; await settle()
  assert.equal(h.snapshots.length, count)
})

test('unmount aborts pending ingestion and cancels already scheduled polling', async t => {
  const clock = fakeClock(t), h = monitorHarness(t)
  let release, signal
  h.client.defaults.adapter = async config => {
    if (config.url.endsWith('/ingest-all')) {
      signal = config.signal
      await new Promise(resolve => { release = resolve })
      return reply(config, { total: 1, results: [{ file: 'one.pdf', status: 'queued' }] })
    }
    return reply(config, config.url.endsWith('/documents') ? [queued] : stats)
  }
  await h.monitor.refresh()
  const pending = h.monitor.ingestAll(); await settle(); h.monitor.dispose()
  const count = h.snapshots.length
  assert.equal(signal.aborted, true)
  assert.equal(clock.queue.size, 0)
  release(); await pending; await settle()
  assert.equal(h.snapshots.length, count)
})

test('manual refresh during an in-flight request waits and starts one fresh read afterward', async t => {
  const clock = fakeClock(t), h = monitorHarness(t)
  let documentRequests = 0, release
  h.client.defaults.adapter = async config => {
    if (config.url.endsWith('/documents')) {
      documentRequests++
      if (documentRequests === 1) await new Promise(resolve => { release = resolve })
      return reply(config, [{ ...queued, status: documentRequests === 1 ? 'queued' : 'completed' }])
    }
    return reply(config, stats)
  }
  const pending = h.monitor.refresh(); await settle()
  await h.monitor.refresh(); await h.monitor.refresh()
  assert.equal(documentRequests, 1)
  release(); await pending; await settle()
  assert.equal(documentRequests, 2)
  assert.equal(h.latest().documents[0].status, 'completed')
  assert.equal(clock.queue.size, 0)
})

test('failed statistics do not hide document job errors or stop monitoring active jobs', async t => {
  const clock = fakeClock(t)
  const h = monitorHarness(t)
  h.client.defaults.adapter = async config => {
    if (config.url.endsWith('/stats')) throw new Error('Stats unavailable')
    return reply(config, [queued, { ...queued, id: 'd2', status: 'failed', error: 'PDF is encrypted' }])
  }
  await h.monitor.refresh()
  assert.equal(h.latest().documents[1]?.error, 'PDF is encrypted')
  assert.equal(clock.queue.size, 1)
  assert.match(h.latest().loadError, /Stats unavailable/)
})
