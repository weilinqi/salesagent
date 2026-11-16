const test = require('node:test')
const assert = require('node:assert/strict')
const { harness, reply, settle } = require('./runtime.cjs')

const detail = {
  id: '11111111-1111-1111-1111-111111111111', scenario_id: 'scenario', status: 'active', current_phase: 'proposal',
  scenario: { id: 'scenario', name: '原来的场景' },
  role_config: { position_level: 'senior', personality: 'hesitant', decision_style: 'risk_averse', voice: 'saved-voice' },
  persona: { name: '原来的客户', title: '采购', company: '原公司' },
  customer_context: { preparation: { product: '原产品', goal: '续约' } },
  investigation_result: { company: '原公司' }, user_context: { difficulty: 'hard', practice_goals: ['discovery'] },
}
const history = [
  { id: 'u1', role: 'user', content: '之前的问题', created_at: '2026-11-08T00:00:00' },
  { id: 'a1', role: 'ai', content: '之前的回答', created_at: '2026-11-08T00:00:01' },
]

function sessionStorage() {
  const data = new Map()
  global.sessionStorage = { getItem: key => data.get(key) || null,
    setItem: (key, value) => data.set(key, value), removeItem: key => data.delete(key) }
  return data
}

test('history loader reads selected session and maps saved messages without creating a session', async () => {
  const h = harness(), requests = []
  h.client.defaults.adapter = async config => {
    requests.push(config)
    return reply(config, config.url.endsWith('/messages') ? history : detail)
  }
  const { loadSessionHistory } = h.load('utils/sessionHistory')
  const result = await loadSessionHistory(detail.id, new AbortController().signal)
  assert.equal(result.session.id, detail.id)
  assert.deepEqual(result.messages.map(item => [item.id, item.type, item.content]),
    [['u1', 'user', '之前的问题'], ['a1', 'ai', '之前的回答']])
  assert.ok(requests.every(config => config.method === 'get' && config.url.includes(detail.id)))
})

test('store restores settings and clears persisted session on reset or end', async () => {
  const data = sessionStorage(), h = harness()
  h.client.defaults.adapter = async config => reply(config, {})
  const { usePracticeStore } = h.load('stores/practiceStore')
  usePracticeStore.getState().resumeSession(detail)
  let state = usePracticeStore.getState()
  assert.equal(state.currentSession.id, detail.id)
  assert.equal(state.selectedRoleConfig.voice, 'saved-voice')
  assert.equal(state.selectedScenario.name, '原来的场景')
  assert.deepEqual(state.currentSession.user_context, detail.user_context)
  assert.deepEqual(state.currentSession.customer_context, detail.customer_context)
  assert.equal(JSON.parse(data.get('sales-agent-practice-session')).id, detail.id)
  state.resetSession()
  assert.equal(data.has('sales-agent-practice-session'), false)
  usePracticeStore.getState().resumeSession(detail)
  await usePracticeStore.getState().endSession()
  assert.equal(data.has('sales-agent-practice-session'), false)
})

function nodes(tree) {
  if (tree == null || typeof tree !== 'object') return []
  if (Array.isArray(tree)) return tree.flatMap(nodes)
  return [tree, ...nodes(tree.props?.children)]
}

function chatHarness(saved = detail, initialSession = { id: 'wrong-session', status: 'active' }) {
  const urls = [], requests = []
  const store = { currentSession: initialSession,
    selectedScenario: null, selectedRoleConfig: null,
    updateSessionPhase() {}, updatePersona() {},
    resumeSession(saved) { store.currentSession = saved; store.selectedScenario = saved.scenario; store.selectedRoleConfig = saved.role_config },
  }
  const h = harness({
    'react-router-dom': { useNavigate: () => () => {}, useSearchParams: () => [new URLSearchParams(`sessionId=${detail.id}`)] },
    '../../stores/practiceStore': { usePracticeStore: () => store },
    '../../hooks/useWebSocket': { useWebSocket: options => { urls.push(options.url); return { isConnected: false, sendMessage() {}, sendStopPlayback() {}, sendVoiceStart() {}, sendVoiceEnd() {}, sendAudioChunk() {} } } },
    '../../hooks/useAudioStream': { useAudioStream: () => ({ stop() {}, playStoredAudio() {} }) },
    '../../components/business/practice/ChatContainer': { __esModule: true, default: 'ChatContainer' },
    '../../components/business/practice/PhaseSummaryModal': { __esModule: true, default: 'Summary' },
    '../../components/business/practice/SpinStageHint': { __esModule: true, default: 'Hint' },
  })
  global.window = { location: { protocol: 'http:', host: 'localhost:5173' } }
  h.client.defaults.adapter = async config => { requests.push(config.url); return reply(config, config.url.endsWith('/messages') ? history : saved) }
  const page = h.load('pages/Practice/PracticeChatPage').default
  return { h, page, store, urls, requests }
}

test('chat honors history URL over stale store and waits for history before connecting', async () => {
  const { h, page, store, urls, requests } = chatHarness()
  h.render(page); h.mount()
  assert.equal(urls.at(-1), null)
  await settle()
  const tree = h.render(page)
  assert.equal(store.currentSession.id, detail.id)
  assert.ok(requests.every(url => url.includes(detail.id)))
  assert.ok(urls.at(-1).endsWith(`/ws/practice/${detail.id}`))
  assert.deepEqual(nodes(tree).find(node => node.type === 'ChatContainer').props.messages.map(item => item.content), ['之前的问题', '之前的回答'])
})

test('fresh browser restores history without cached session; completed records stay read-only', async () => {
  const { h, page, store, urls } = chatHarness({ ...detail, status: 'completed' }, null)
  h.render(page); h.mount(); await settle()
  const tree = h.render(page)
  assert.equal(store.currentSession.id, detail.id)
  assert.ok(urls.every(url => url === null))
  assert.equal(nodes(tree).find(node => node.type === 'ChatContainer').props.isDisabled, true)
})

test('failed history load cannot open a different cached session and offers retry', async () => {
  const { h, page, urls } = chatHarness()
  h.client.defaults.adapter = async () => { throw new Error('offline') }
  h.render(page); h.mount(); await settle()
  const tree = h.render(page)
  assert.ok(nodes(tree).some(node => node.props?.role === 'alert'))
  assert.ok(urls.every(url => url === null))
  assert.ok(nodes(tree).some(node => node.type === 'button' && node.props.children === '重新加载历史记录'))
})

test('unmount cancels pending history so late responses cannot replace the current session', async () => {
  const { h, page, store } = chatHarness()
  const pending = []
  h.client.defaults.adapter = config => new Promise(resolve => pending.push(() => resolve(reply(config, config.url.endsWith('/messages') ? history : detail))))
  h.render(page); const cleanups = h.mount(); await settle()
  cleanups.forEach(cleanup => cleanup())
  pending.forEach(resolve => resolve()); await settle()
  assert.equal(store.currentSession.id, 'wrong-session')
})
