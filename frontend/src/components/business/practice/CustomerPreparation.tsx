import { useEffect, useRef, useState } from 'react'
import axios from 'axios'
import SalesMaterialPreview from './SalesMaterialPreview'
import SalesSuggestions from './SalesSuggestions'

export type PreparationProfile = Record<'industry' | 'product' | 'target' | 'organization' | 'needs' | 'preferences' | 'goal', string>
const fields: [keyof PreparationProfile, string, string][] = [
  ['industry', '推销行业', '待补充'], ['product', '产品或服务', '必填'],
  ['target', '对象身份／职务', '必填'], ['organization', '关联公司／机构／人物', '可选'],
  ['needs', '需求与使用场景', '待补充'], ['preferences', '喜好与顾虑', '可选'],
  ['goal', '本次练习目标', '必填'],
]
const empty: PreparationProfile = { industry: '', product: '', target: '', organization: '', needs: '', preferences: '', goal: '' }
type ResearchSource = { title: string; summary: string; url: string; date?: string; publisher?: string; topic?: string }
export type Background = { digest_version?: number; roles?: Record<string, string>; insights?: { title: string; summary: string; caveat?: string; sources: ResearchSource[] }[]; search_key?: string; gaps?: string[]; organization: string; overview?: { title: string; summary: string; url: string; date?: string; publisher?: string; topic?: string } | null; sources: { title: string; summary: string; url: string; date?: string; publisher?: string; topic?: string }[]; notice: string; checked_at?: string }

export default function CustomerPreparation({ onStart, starting, initialProfile, trainingMode = 'full', onProfileChange }: { trainingMode?: 'full' | 'rejection'; onProfileChange?: (profile: PreparationProfile) => void; initialProfile?: Partial<PreparationProfile>; onStart: (profile: PreparationProfile, background?: Background) => Promise<void>; starting: boolean }) {
  const [profile, setProfile] = useState<PreparationProfile>(() => ({ ...empty, ...initialProfile }))
  const [message, setMessage] = useState('')
  const [questions, setQuestions] = useState<string[]>([])
  const [collected, setCollected] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [background, setBackground] = useState<Background | null>(null)
  const [searching, setSearching] = useState(false)
  const [showMaterials, setShowMaterials] = useState(false)
  const cache = useRef(new Map<string, { data: Background; at: number }>())
  const request = useRef<AbortController | null>(null)
  const generation = useRef(0)
  const current = useRef(profile)
  current.current = profile
  useEffect(() => { onProfileChange?.(profile) }, [profile, onProfileChange])
  const ready = ['product', 'target', 'goal'].every(key => {
    const value = profile[key as keyof PreparationProfile].trim()
    return value && !['未知', '不清楚', '不知道', '待补充', '待了解'].includes(value)
  })

  useEffect(() => () => { generation.current++; request.current?.abort() }, [])
  useEffect(() => {
    setBackground(null)
    if ((!profile.organization.trim() && !profile.product.trim()) || starting) { setSearching(false); return }
    const cacheKey = [profile.organization, profile.product, profile.needs, profile.target].map(value => value.trim()).join('\n')
    const cached = cache.current.get(cacheKey)
    if (cached && Date.now() - cached.at < 300000) { setBackground(cached.data); setSearching(false); return }
    const controller = new AbortController()
    setSearching(true)
    const timer = setTimeout(() => {
      axios.post<Background>('/api/v1/practice/preparation/background', { organization: profile.organization.trim(), product: profile.product, needs: profile.needs, target: profile.target }, { signal: controller.signal, timeout: 45000 })
        .then(({ data }) => { if (!controller.signal.aborted) { setBackground(data); if (data.insights?.length) { if (cache.current.size >= 10) cache.current.delete(cache.current.keys().next().value!); cache.current.set(cacheKey, { data, at: Date.now() }) } } })
        .catch(() => { if (!controller.signal.aborted) setBackground({
          organization: profile.organization.trim(), sources: [],
          notice: '公开资料检索暂不可用；此 PDF 只保留已确认信息，不代表已核实课程、价格或规则。',
          gaps: ['公开资料检索暂不可用，课程、价格与规则需要后续核实。'],
          checked_at: new Date().toISOString(),
          search_key: [profile.organization, profile.product, profile.needs, profile.target].map(value => value.trim()).join('\n'),
        }) })
        .finally(() => { if (!controller.signal.aborted) setSearching(false) })
    }, 500)
    return () => { clearTimeout(timer); controller.abort() }
  }, [profile.organization, profile.product, profile.needs, profile.target, starting])

  async function collect() {
    if (!message.trim() || busy || starting) return
    const snapshot = { ...profile }
    const turn = ++generation.current
    request.current?.abort()
    request.current = new AbortController()
    setBusy(true); setError('')
    // Fast extraction runs beside the model; late responses cannot overwrite edits.
    void axios.post<{ profile: PreparationProfile }>('/api/v1/practice/preparation/preview', { profile: snapshot, message }, { signal: request.current.signal, timeout: 5000 })
      .then(({ data }) => {
        if (generation.current !== turn) return
        setProfile(previous => Object.fromEntries(fields.map(([key]) => [key, previous[key] !== snapshot[key] ? previous[key] : data.profile[key]])) as PreparationProfile)
      }).catch(() => { /* The AI request remains the primary extraction path. */ })
    try {
      const { data } = await axios.post<{ profile: PreparationProfile; questions: string[]; warning: string; success?: boolean }>('/api/v1/practice/preparation/collect', { profile: snapshot, message }, { signal: request.current.signal, timeout: 45000 })
      if (generation.current !== turn) return
      // Do not overwrite edits made while the AI request was running.
      setProfile(previous => Object.fromEntries(fields.map(([key]) => [key, previous[key] !== snapshot[key] ? previous[key] : data.profile[key]])) as PreparationProfile)
      generation.current++; setBusy(false); setQuestions(data.questions.slice(0, 2)); setError(data.warning); if (data.success !== false && !data.warning) setMessage(''); setCollected(true)
    } catch {
      if (generation.current === turn) { setError('整理暂时失败，请重试或直接填写下方列表。'); setCollected(true) }
    } finally { if (generation.current === turn) setBusy(false) }
  }

  async function start() {
    if (!ready || starting || searching) return
    generation.current++; request.current?.abort(); setBusy(false)
    await onStart(Object.fromEntries(fields.map(([key]) => [key, current.current[key].trim()])) as PreparationProfile, background?.search_key === [current.current.organization, current.current.product, current.current.needs, current.current.target].map(value => value.trim()).join('\n') ? background : undefined)
  }

  return <section className="space-y-5">
    <div className="rounded-lg bg-blue-50 p-4">
      <h2 className="font-semibold text-gray-900">先简单介绍你的推销对象</h2>
      <p className="mt-2 text-sm text-gray-600">提示：推销什么 · 对象是谁 · 所在公司或机构 · 已知需求 · 想达成什么目标。知道多少说多少。</p>
      <p className="mt-2 text-sm text-gray-500">例如：我想向一家制造公司的采购经理介绍设备，希望预约演示，其他情况暂时不清楚。</p>
    </div>
    {questions.length > 0 && <ul className="list-disc pl-5 text-sm text-gray-700">{questions.map(q => <li key={q}>{q}</li>)}</ul>}
    <label className="block text-sm font-medium">{collected ? '继续补充（也可直接修改列表）' : '初步介绍'}
      <textarea value={message} onChange={e => setMessage(e.target.value)} disabled={busy || starting} maxLength={4000} rows={3} className="mt-2 w-full rounded-lg border p-3" placeholder="请简单介绍你的销售任务和对象…" />
    </label>
    <button type="button" onClick={() => void collect()} disabled={busy || starting || !message.trim()} className="rounded-lg bg-primary px-4 py-2 text-white disabled:opacity-40">{busy ? '已开始自动填入，AI 正在完善…' : collected ? '补充并整理' : '整理信息'}</button>
    {error && <p role="alert" className="text-sm text-amber-700">{error}</p>}
    <div className="rounded-lg border divide-y">
      <h3 className="p-3 font-medium">对象信息 · 可直接修改</h3>
      {fields.map(([key, label, requirement]) => <label key={key} className="flex flex-col gap-2 p-3 sm:flex-row sm:items-center">
        <span className="text-sm sm:w-44 shrink-0">{label} <span className="text-xs text-gray-400">{requirement}</span></span>
        <input aria-label={label} value={profile[key]} maxLength={1000} disabled={starting} onChange={e => setProfile(prev => ({ ...prev, [key]: e.target.value }))} placeholder={requirement} className="min-w-0 flex-1 rounded border px-3 py-2 text-sm" />
      </label>)}
    </div>
    <button type="button" aria-expanded={showMaterials} aria-controls="sales-materials" onClick={() => setShowMaterials(value => !value)} className="min-h-14 rounded-lg bg-primary px-8 py-3 text-lg font-medium text-white hover:bg-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600">{showMaterials ? '收起资料' : '展示资料'}</button>
    {searching && <p role="status" className="text-sm text-blue-600">正在生成相关资料...</p>}
    <div id="sales-materials" hidden={!showMaterials} className="space-y-4">
    {!searching && !background && <p className="text-sm text-gray-500">填写产品和对象信息后，将自动生成相关资料。</p>}
    {background && <div className="rounded-lg bg-gray-50 p-3 text-sm"><h3 className="font-medium">背景介绍：{background.organization}</h3>{background.digest_version ? <ol className="list-decimal pl-5 space-y-4">{background.insights?.map((item, i) => <li key={i}><h4 className="font-medium">{item.title}</h4><p className="mt-1">{item.summary}</p><ul className="mt-2 space-y-1 text-xs">{item.sources.map(source => <li key={source.url}><a href={source.url} target="_blank" rel="noreferrer" className="text-primary underline">{source.title}</a><span className="text-gray-500"> · {source.date || '日期未提供'}</span></li>)}</ul></li>)}</ol> : <><div className="mb-3"><h4 className="font-medium">背景概况</h4>{background.overview ? <><p>{background.overview.summary}</p><a href={background.overview.url} target="_blank" rel="noreferrer" className="text-primary underline">来源：{background.overview.title}</a></> : <p className="text-gray-500">暂未查到可靠的背景概况。</p>}</div><ol className="list-decimal pl-5 space-y-3">{background.sources.map((source, i) => <li key={i}><a href={source.url} target="_blank" rel="noreferrer" className="text-primary underline">{source.title}</a><p>{source.summary}</p><p className="text-xs text-gray-500">{source.topic} · {source.publisher} · {source.date || '日期未提供'}</p></li>)}</ol></>}{background.gaps?.filter(gap => /失败|超时|重试|未完成|不可用/.test(gap)).map((gap, i) => <p key={i} className="mt-2 text-amber-700">{gap}</p>)}<p className="mt-3 text-xs text-gray-500">信息可能不准确或存在时效差异，请仔细甄别，并以来源原文及机构最新公布的信息为准。</p>{background.checked_at && <p className="mt-2 text-xs text-gray-400">查询时间：{new Date(background.checked_at).toLocaleString()}</p>}</div>}
    {!searching && background?.search_key === [profile.organization, profile.product, profile.needs, profile.target].map(value => value.trim()).join('\n') && <SalesMaterialPreview key={JSON.stringify(profile) + background.checked_at} profile={profile} background={background} />}
    </div>
    {profile.product.trim() && profile.target.trim() && <SalesSuggestions key={trainingMode + JSON.stringify(profile)} trainingMode={trainingMode} profile={profile} />}
    <p className="text-xs text-gray-500">未填资料保持未知。模拟设定：客户沟通谨慎、适度追问，依据你的回应调整态度。</p>
    {ready ? <button type="button" disabled={starting || searching} onClick={() => void start()} className="w-full rounded-lg bg-primary p-3 font-medium text-white disabled:opacity-40">{searching ? '正在准备对话前资料…' : starting ? '正在进入对练…' : '直接进入对练'}</button> : <p className="text-sm text-gray-500">明确产品或服务、对象身份、练习目标后，即可直接进入对练。</p>}
  </section>
}
