import { useEffect, useRef, useState } from 'react'
import axios from 'axios'
import type { Background, PreparationProfile } from './CustomerPreparation'

type SuggestionItem = { title: string; speech: string }

function localSuggestions(trainingMode: 'full' | 'rejection' | 'price_objection' | 'follow_up', profile: PreparationProfile): SuggestionItem[] {
  if (trainingMode === 'price_objection') {
    const brandA = profile.price_brand_a || '当前方案'
    const brandB = profile.price_brand_b || '对比方案'
    const aspect = profile.price_comparison_aspect || '价格'
    return [
      { title: '先问清比较对象', speech: `您说${brandA}比${brandB}贵，主要是${aspect}上的差距，还是课程内容也不一样？` },
      { title: '确认最在意的结果', speech: '除了价格，您最希望孩子在这门课里得到什么结果？' },
      { title: '拆开看费用', speech: `如果把${aspect}和包含的服务分开看，您最想先确认哪一部分？` },
      { title: '了解预算范围', speech: '方便说说您目前大概希望把预算控制在什么范围吗？' },
      { title: '推进下一步', speech: '如果我把价格和包含内容逐项说明，您愿意再比较一次吗？' },
    ]
  }
  if (trainingMode === 'rejection') {
    return [
      { title: '先接住顾虑', speech: '我理解您现在暂时不考虑，您最担心的是哪一方面？' },
      { title: '确认原因', speech: '是预算、效果还是之前的体验让您有顾虑？' },
      { title: '不急着成交', speech: '今天不急着做决定，我只想先确认您真正担心的问题。' },
      { title: '留一个下一步', speech: '如果我补充一份更有针对性的资料，您愿意再看看吗？' },
    ]
  }
  if (trainingMode === 'follow_up') {
    const customer = profile.customer_name || profile.organization || '您'
    const progress = profile.current_progress || profile.needs || '上次沟通后的情况'
    const expectation = profile.follow_up_expectation || profile.goal || '确认下一步安排'
    return [
      { title: '自然接续上次沟通', speech: `${customer}，您好，想跟进一下我们上次沟通的情况，现在方便聊两分钟吗？` },
      { title: '确认最新进度', speech: `上次您提到${progress}，这段时间有没有新的变化？` },
      { title: '核对当前顾虑', speech: '目前还有哪些问题或顾虑，您希望我优先补充说明？' },
      { title: '约定明确下一步', speech: `如果这次先把${expectation}确认下来，您觉得下一步怎样安排最合适？` },
    ]
  }
  const product = profile.product || '这个方案'
  return [
    { title: '了解当前情况', speech: `您现在对${product}最想先了解哪一方面？` },
    { title: '确认目标', speech: `您希望这次使用${product}后，最重要的变化是什么？` },
    { title: '了解顾虑', speech: '目前还有哪些因素会让您犹豫？' },
    { title: '推进下一步', speech: '如果我把关键信息说明清楚，您愿意继续了解吗？' },
  ]
}

export default function SalesSuggestions({ profile, background, trainingMode = 'full' }: { trainingMode?: 'full' | 'rejection' | 'price_objection' | 'follow_up'; profile: PreparationProfile; background?: Background }) {
  const [items, setItems] = useState<SuggestionItem[]>(() => localSuggestions(trainingMode, profile))
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const history = useRef<SuggestionItem[]>([])
  const payload = JSON.stringify({ training_mode: trainingMode, profile, background: background || {} })
  useEffect(() => {
    const controller = new AbortController()
    setBusy(true); setError('')
    axios.post('/api/v1/practice/preparation/suggestions', { ...JSON.parse(payload), previous: history.current }, { signal: controller.signal, timeout: 30000 })
      .then(({ data }) => { if (!Array.isArray(data.items) || !data.items.length || data.items.some((item: { title?: unknown; speech?: unknown }) => !item || typeof item.title !== 'string' || typeof item.speech !== 'string')) throw new Error('Invalid suggestions'); if (!controller.signal.aborted) { const next = data.items.slice(0, 5); setItems(next); history.current = [...history.current, ...next].slice(-30); if (data.fallback) setError('AI 生成较慢，已先展示本地可用角度。可点击“更多角度”继续生成。') } })
      .catch(err => {
        if (controller.signal.aborted) return
        const status = axios.isAxiosError(err) ? err.response?.status : undefined
        setItems(localSuggestions(trainingMode, profile))
        setError(status === 404 ? '后端尚未加载话术接口，已先展示本地角度；重启后端后可继续生成。' : status === 401 ? '登录已过期，已先展示本地角度；请重新登录。' : axios.isAxiosError(err) && err.code === 'ECONNABORTED' ? '话术生成超时，已先展示本地可用角度。可点击“更多角度”重试。' : '话术建议暂未生成，已先展示本地可用角度。')
      })
      .finally(() => { if (!controller.signal.aborted) setBusy(false) })
    return () => controller.abort()
  }, [payload, attempt])
  return <section aria-label="场景参考话术" className="space-y-3 pt-4">
    <h3 className="font-medium text-gray-900">这个场景，可以怎么聊</h3>
    {busy && <p role="status" className="text-sm text-gray-500">正在准备场景话术…</p>}
    {error && <div role="alert" className="text-sm text-amber-700">{error} <button type="button" onClick={() => setAttempt(n => n + 1)} className="underline">重新生成</button></div>}
    <div className="grid gap-3 sm:grid-cols-2">{items.map((item, i) => <article key={i} className="rounded-3xl rounded-bl-md border border-blue-200/60 bg-blue-50/40 p-4 backdrop-blur-sm">
      <h4 className="text-sm font-semibold text-blue-900">{item.title}</h4>
      <p className="mt-2 text-sm leading-relaxed text-gray-800">{item.speech}</p>
    </article>)}</div>
    <button type="button" disabled={busy} onClick={() => setAttempt(n => n + 1)} className="rounded-full border border-blue-200 px-3 py-1 text-xs text-blue-700 disabled:opacity-50">{busy ? '正在生成…' : '更多角度'}</button>
  </section>
}
