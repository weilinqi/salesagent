import { useEffect, useRef, useState } from 'react'
import axios from 'axios'
import type { Background, PreparationProfile } from './CustomerPreparation'

export default function SalesSuggestions({ profile, background, trainingMode = 'full' }: { trainingMode?: 'full' | 'rejection'; profile: PreparationProfile; background?: Background }) {
  const [items, setItems] = useState<{ title: string; speech: string }[]>([])
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const history = useRef<{ title: string; speech: string }[]>([])
  const payload = JSON.stringify({ training_mode: trainingMode, profile, background: background || {} })
  useEffect(() => {
    const controller = new AbortController()
    setBusy(true); setError('')
    axios.post('/api/v1/practice/preparation/suggestions', { ...JSON.parse(payload), previous: history.current }, { signal: controller.signal, timeout: 25000 })
      .then(({ data }) => { if (!Array.isArray(data.items) || !data.items.length || data.items.some((item: { title?: unknown; speech?: unknown }) => !item || typeof item.title !== 'string' || typeof item.speech !== 'string')) throw new Error('Invalid suggestions'); if (!controller.signal.aborted) { const next = data.items.slice(0, 5); setItems(next); history.current = [...history.current, ...next].slice(-30) } })
      .catch(err => {
        if (controller.signal.aborted) return
        const status = axios.isAxiosError(err) ? err.response?.status : undefined
        setError(status === 404 ? '后端尚未加载话术接口，请重启后端后重试。' : status === 401 ? '登录已过期，请重新登录。' : axios.isAxiosError(err) && err.code === 'ECONNABORTED' ? '话术生成超时，请重试。' : '话术建议暂未生成，请重试。')
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
