import { useEffect, useRef, useState } from 'react'
import axios from 'axios'
import SalesMaterialPreview from './SalesMaterialPreview'
import SalesSuggestions from './SalesSuggestions'

export type PreparationProfile = Record<'industry' | 'product' | 'target' | 'organization' | 'needs' | 'preferences' | 'goal' |
  'price_brand_a' | 'price_brand_b' | 'price_brand_c' | 'price_comparison_aspect' | 'price_concern', string>
const fields: [keyof PreparationProfile, string, string][] = [
  ['industry', '推销行业', '待补充'], ['product', '产品或服务', '必填'],
  ['target', '对象身份／职务', '必填'], ['organization', '关联公司／机构／人物', '可选'],
  ['needs', '需求与使用场景', '待补充'], ['preferences', '喜好与顾虑', '可选'],
  ['goal', '本次练习目标', '必填'],
]
const priceFields: [keyof PreparationProfile, string, string][] = [
  ['price_brand_a', 'A·我方品牌／机构', '必填'], ['price_brand_b', 'B·对比品牌／机构', '必填'],
  ['price_brand_c', 'C·其他对比品牌／机构', '可选'], ['price_comparison_aspect', '价格比较方面', '必填'],
  ['price_concern', '客户的具体价格顾虑', '必填'],
]
const priceDisplayFields: [keyof PreparationProfile, string, string][] = [
  ['target', '客户身份／职务', '必填'], ['organization', '客户所属机构／关联人物', '可选'],
  ['industry', '推销行业', '待补充'], ['price_brand_a', 'A·我方品牌／机构', '必填'],
  ['price_brand_b', 'B·对比品牌／机构', '必填'], ['price_brand_c', 'C·其他对比品牌／机构', '可选'],
  ['product', '比较的产品或班型', '必填'], ['price_comparison_aspect', '价格比较方面', '必填'],
  ['price_concern', '客户的具体价格顾虑', '必填'], ['goal', '本次练习目标', '必填'],
]
const empty: PreparationProfile = {
  industry: '', product: '', target: '', organization: '', needs: '', preferences: '', goal: '',
  price_brand_a: '', price_brand_b: '', price_brand_c: '', price_comparison_aspect: '', price_concern: '',
}
const unknownValues = new Set(['', '未知', '不清楚', '不知道', '待补充', '待了解', '太贵', '很贵', '价格高'])
const isKnown = (value: string) => !unknownValues.has(value.trim())
type ResearchSource = { title: string; summary: string; url: string; date?: string; publisher?: string; topic?: string }
type PriceEvidence = { price: string; snippet: string; title: string; url: string; date?: string }
type PriceComparison = { aspect: string; entries: { slot: string; brand: string; evidence: PriceEvidence[] }[]; market_reference: PriceEvidence[]; organized?: string[]; notice: string }
export type Background = { digest_version?: number; roles?: Record<string, string>; insights?: { title: string; summary: string; caveat?: string; sources: ResearchSource[] }[]; search_key?: string; gaps?: string[]; basic_background?: string; organization: string; overview?: { title: string; summary: string; url: string; date?: string; publisher?: string; topic?: string } | null; sources: { title: string; summary: string; url: string; date?: string; publisher?: string; topic?: string }[]; notice: string; checked_at?: string; price_comparison?: PriceComparison }

function localPriceComparison(profile: PreparationProfile): PriceComparison | undefined {
  if (!profile.price_brand_a && !profile.price_brand_b) return undefined
  const evidence = profile.price_concern ? [{
    price: '客户填写', snippet: profile.price_concern, title: '客户填写的价格比较信息', url: '',
  }] : []
  return {
    aspect: profile.price_comparison_aspect || '价格',
    entries: [
      { slot: 'A', brand: profile.price_brand_a || '未填写', evidence },
      { slot: 'B', brand: profile.price_brand_b || '未填写', evidence },
      ...(profile.price_brand_c ? [{ slot: 'C', brand: profile.price_brand_c, evidence }] : []),
    ],
    market_reference: [],
    organized: [`A｜${profile.price_brand_a || '未填写'}：保留客户填写的价格比较信息，等待公开来源补充。`, `B｜${profile.price_brand_b || '未填写'}：保留客户填写的价格比较信息，等待公开来源补充。`],
    notice: '联网检索超时或暂不可用；以上内容仅来自你填写的价格比较信息，未完成外部核验。',
  }
}

export default function CustomerPreparation({ onStart, starting, initialProfile, trainingMode = 'full', onProfileChange }: { trainingMode?: 'full' | 'rejection' | 'price_objection'; onProfileChange?: (profile: PreparationProfile) => void; initialProfile?: Partial<PreparationProfile>; onStart: (profile: PreparationProfile, background?: Background) => Promise<void>; starting: boolean }) {
  const [profile, setProfile] = useState<PreparationProfile>(() => ({ ...empty, ...initialProfile }))
  const [message, setMessage] = useState('')
  const [questions, setQuestions] = useState<string[]>([])
  const [collected, setCollected] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [background, setBackground] = useState<Background | null>(null)
  const [searching, setSearching] = useState(false)
  const [showMaterials, setShowMaterials] = useState(false)
  const [searchRevision, setSearchRevision] = useState(0)
  const cache = useRef(new Map<string, { data: Background; at: number }>())
  const request = useRef<AbortController | null>(null)
  const generation = useRef(0)
  const current = useRef(profile)
  current.current = profile
  useEffect(() => { onProfileChange?.(profile) }, [profile, onProfileChange])
  const brandsDiffer = isKnown(profile.price_brand_a) && isKnown(profile.price_brand_b) && profile.price_brand_a.trim().toLowerCase() !== profile.price_brand_b.trim().toLowerCase()
  const priceFieldReady = (key: keyof PreparationProfile) => {
    if (key === 'price_concern') return isKnown(profile[key])
    if (key === 'price_brand_a' || key === 'price_brand_b') return isKnown(profile[key]) && brandsDiffer
    return isKnown(profile[key])
  }
  const visibleFields = trainingMode === 'price_objection' ? priceDisplayFields : fields
  const missingRequiredFields = visibleFields.filter(([key, , requirement]) => requirement === '必填' && !(
    trainingMode === 'price_objection' ? priceFieldReady(key) : isKnown(profile[key])
  ))
  const ready = missingRequiredFields.length === 0
  const missingRequiredLabels = missingRequiredFields.map(([, label]) => label)
  const sourceCount = (topic: string) => background?.sources.filter(source => source.topic?.startsWith(topic)).length || 0
  const priceComparison = background?.price_comparison || (trainingMode === 'price_objection' ? localPriceComparison(profile) : undefined)

  useEffect(() => () => { generation.current++; request.current?.abort() }, [])
  useEffect(() => {
    setBackground(null)
    const priceSearchReady = trainingMode !== 'price_objection' || (
      isKnown(profile.price_brand_a) && isKnown(profile.price_brand_b) && isKnown(profile.price_comparison_aspect)
    )
    if ((!profile.organization.trim() && !profile.product.trim()) || !priceSearchReady || starting) { setSearching(false); return }
    const cacheKey = [trainingMode, profile.organization, profile.product, profile.needs, profile.target,
      profile.price_brand_a, profile.price_brand_b, profile.price_brand_c, profile.price_comparison_aspect].map(value => value.trim()).join('\n')
    const cached = cache.current.get(cacheKey)
    if (cached && Date.now() - cached.at < 300000) { setBackground(cached.data); setSearching(false); return }
    const controller = new AbortController()
    setSearching(true)
    const timer = setTimeout(() => {
      axios.post<Background>('/api/v1/practice/preparation/background', {
        organization: profile.organization.trim(), product: profile.product, needs: profile.needs, target: profile.target,
        training_mode: trainingMode, price_brand_a: profile.price_brand_a, price_brand_b: profile.price_brand_b,
        price_brand_c: profile.price_brand_c, price_comparison_aspect: profile.price_comparison_aspect,
      }, { signal: controller.signal, timeout: trainingMode === 'price_objection' ? 30000 : 75000 })
        .then(({ data }) => { if (!controller.signal.aborted) { setBackground(data); if (data.insights?.length) { if (cache.current.size >= 10) cache.current.delete(cache.current.keys().next().value!); cache.current.set(cacheKey, { data, at: Date.now() }) } } })
        .catch(() => { if (!controller.signal.aborted) setBackground({
          organization: profile.organization.trim(), sources: [],
          notice: '公开资料检索暂不可用；此 PDF 只保留已确认信息，不代表已核实课程、价格或规则。',
          gaps: ['联网检索超时或暂不可用，课程、价格与规则需要后续核实。'],
          checked_at: new Date().toISOString(),
          search_key: [profile.organization, profile.product, profile.needs, profile.target].map(value => value.trim()).join('\n'),
          price_comparison: trainingMode === 'price_objection' ? localPriceComparison(profile) : undefined,
        }) })
        .finally(() => { if (!controller.signal.aborted) setSearching(false) })
    }, 500)
    return () => { clearTimeout(timer); controller.abort() }
  }, [profile.organization, profile.product, profile.needs, profile.target, profile.price_brand_a,
    profile.price_brand_b, profile.price_brand_c, profile.price_comparison_aspect, trainingMode, starting, searchRevision])

  async function collect() {
    if (!message.trim() || busy || starting) return
    const snapshot = { ...profile }
    const turn = ++generation.current
    request.current?.abort()
    request.current = new AbortController()
    setBusy(true); setError('')
    // Fast extraction runs beside the model; late responses cannot overwrite edits.
    void axios.post<{ profile: PreparationProfile }>('/api/v1/practice/preparation/preview', { profile: snapshot, message, training_mode: trainingMode }, { signal: request.current.signal, timeout: 5000 })
      .then(({ data }) => {
        if (generation.current !== turn) return
        setProfile(previous => Object.fromEntries([...fields, ...priceFields].map(([key]) => [key, previous[key] !== snapshot[key] ? previous[key] : data.profile[key]])) as PreparationProfile)
      }).catch(() => { /* The AI request remains the primary extraction path. */ })
    try {
      const { data } = await axios.post<{ profile: PreparationProfile; questions: string[]; warning: string; success?: boolean }>('/api/v1/practice/preparation/collect', { profile: snapshot, message, training_mode: trainingMode }, { signal: request.current.signal, timeout: 45000 })
      if (generation.current !== turn) return
      // Do not overwrite edits made while the AI request was running.
      setProfile(previous => Object.fromEntries([...fields, ...priceFields].map(([key]) => [key, previous[key] !== snapshot[key] ? previous[key] : data.profile[key]])) as PreparationProfile)
      generation.current++; setBusy(false); setQuestions(data.questions.slice(0, 2)); setError(data.warning); if (data.success !== false && !data.warning) setMessage(''); setCollected(true)
    } catch {
      if (generation.current === turn) { setError('整理暂时失败，请重试或直接填写下方列表。'); setCollected(true) }
    } finally { if (generation.current === turn) setBusy(false) }
  }

  async function start() {
    if (!ready || starting || searching) return
    generation.current++; request.current?.abort(); setBusy(false)
      await onStart(Object.fromEntries([...fields, ...priceFields].map(([key]) => [key, current.current[key].trim()])) as PreparationProfile, background?.search_key === [current.current.organization, current.current.product, current.current.needs, current.current.target].map(value => value.trim()).join('\n') ? background : undefined)
  }

  return <section className="space-y-5">
    <div className="rounded-lg bg-blue-50 p-4">
      <h2 className="font-semibold text-gray-900">先简单介绍你的推销对象</h2>
      <p className="mt-2 text-sm text-gray-600">{trainingMode === 'price_objection'
        ? '提示：推销什么 · 对象是谁 · A 是哪家机构 · B 是哪家机构 · 客户在价格比较方面“有什么顾虑” · 想达成什么目标。'
        : '提示：推销什么 · 对象是谁 · 所在公司或机构 · 已知需求 · 想达成什么目标。知道多少说多少。'}</p>
      <p className="mt-2 text-sm text-gray-500">{trainingMode === 'price_objection'
        ? '例如：我从事教育培训行业，向石家庄某重点中学的高三学生家长介绍学而思高三数学一对一课程；客户在单课时价格方面有顾虑，认为学而思每课时约600元，比新东方同类课程每课时约450元贵，担心多出的费用不能带来更好效果，本次希望练习如何说明课程价值并争取试听。品牌和金额均为测试示例。'
        : '例如：我想向一家制造公司的采购经理介绍设备，希望预约演示，其他情况暂时不清楚。'}</p>
    </div>
    {questions.length > 0 && <ul className="list-disc pl-5 text-sm text-gray-700">{questions.map(q => <li key={q}>{q}</li>)}</ul>}
    <label className="block text-sm font-medium">{collected ? '继续补充（也可直接修改列表）' : '初步介绍'}
      <textarea value={message} onChange={e => setMessage(e.target.value)} disabled={busy || starting} maxLength={4000} rows={4} className="mt-2 w-full rounded-lg border p-3" placeholder={trainingMode === 'price_objection'
        ? '请清楚说明：A 品牌、B 品牌、比较的产品或班型，以及客户在价格比较方面有什么具体顾虑…'
        : '请简单介绍你的销售任务和对象…'} />
    </label>
    <button type="button" onClick={() => void collect()} disabled={busy || starting || !message.trim()} className="rounded-lg bg-primary px-4 py-2 text-white disabled:opacity-40">{busy ? '已开始自动填入，AI 正在完善…' : collected ? '补充并整理' : '整理信息'}</button>
    {error && <p role="alert" className="text-sm text-amber-700">{error}</p>}
    <div className="rounded-lg border divide-y">
      <h3 className="p-3 font-medium">{trainingMode === 'price_objection' ? '对象与价格信息 · 可直接修改' : '对象信息 · 可直接修改'}</h3>
      {visibleFields.map(([key, label, requirement]) => <label key={key} className="flex flex-col gap-2 p-3 sm:flex-row sm:items-start">
        <span className="text-sm sm:w-44 shrink-0">{label} <span className="text-xs text-gray-400">{requirement}</span></span>
        {key === 'price_concern'
          ? <textarea aria-label={label} value={profile[key]} maxLength={1000} disabled={starting} rows={3} onChange={event => setProfile(prev => ({ ...prev, [key]: event.target.value }))} placeholder="用“客户认为/担心……”写清 A 与 B 在价格比较方面的具体顾虑" className="min-w-0 flex-1 rounded border px-3 py-2 text-sm" />
          : <input aria-label={label} value={profile[key]} maxLength={1000} disabled={starting} onChange={event => setProfile(prev => ({ ...prev, [key]: event.target.value }))} placeholder={key === 'price_comparison_aspect' ? '例如：单课时价格、课程总价、年费或课时包' : key === 'product' && trainingMode === 'price_objection' ? '例如：高三数学一对一、雅思6.5强化班' : requirement} className="min-w-0 flex-1 rounded border px-3 py-2 text-sm" />}
      </label>)}
    </div>
    <button type="button" aria-expanded={showMaterials} aria-controls="sales-materials" onClick={() => setShowMaterials(value => !value)} className="min-h-14 rounded-lg bg-primary px-8 py-3 text-lg font-medium text-white hover:bg-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600">{showMaterials ? '收起资料' : '展示资料'}</button>
    {searching && <p role="status" className="text-sm text-blue-600">正在分别检索 A/B 和市场资料，可能需要几十秒…</p>}
    <div id="sales-materials" hidden={!showMaterials} className="space-y-4">
    {!searching && !background && <p className="text-sm text-gray-500">填写产品和对象信息后，将自动生成相关资料。</p>}
    {background && <div className="rounded-lg bg-gray-50 p-3 text-sm"><h3 className="font-medium">背景介绍：{background.organization}</h3>{background.digest_version && background.overview && <div className="my-3 rounded bg-white p-3"><h4 className="font-medium">机构背景</h4><p className="mt-1">{background.overview.summary}</p><a href={background.overview.url} target="_blank" rel="noreferrer" className="text-primary underline">来源：{background.overview.title}</a></div>}{!background.overview && background.basic_background && <p className="my-3 rounded bg-white p-3 text-gray-700">{background.basic_background}</p>}{background.digest_version ? background.insights?.length ? <ol className="list-decimal pl-5 space-y-4">{background.insights.map((item, i) => <li key={i}><h4 className="font-medium">{item.title}</h4><p className="mt-1">{item.summary}</p><ul className="mt-2 space-y-1 text-xs">{item.sources.map(source => <li key={source.url}><a href={source.url} target="_blank" rel="noreferrer" className="text-primary underline">{source.title}</a><span className="text-gray-500"> · {source.date || '日期未提供'}</span></li>)}</ul></li>)}</ol> : <p className="text-gray-500">暂未整理出可核验的公开资料；上方已列出本次情景中的已知信息。</p> : <><div className="mb-3"><h4 className="font-medium">背景概况</h4>{background.overview ? <><p>{background.overview.summary}</p><a href={background.overview.url} target="_blank" rel="noreferrer" className="text-primary underline">来源：{background.overview.title}</a></> : <p className="text-gray-500">暂未查到可靠的背景概况。</p>}</div><ol className="list-decimal pl-5 space-y-3">{background.sources.map((source, i) => <li key={i}><a href={source.url} target="_blank" rel="noreferrer" className="text-primary underline">{source.title}</a><p>{source.summary}</p><p className="text-xs text-gray-500">{source.topic} · {source.publisher} · {source.date || '日期未提供'}</p></li>)}</ol></>}{background.gaps?.filter(gap => /失败|超时|重试|未完成|不可用/.test(gap)).map((gap, i) => <p key={i} className="mt-2 text-amber-700">{gap}</p>)}<p className="mt-3 text-xs text-gray-500">信息可能不准确或存在时效差异，请仔细甄别，并以来源原文及机构最新公布的信息为准。</p>{background.checked_at && <p className="mt-2 text-xs text-gray-400">查询时间：{new Date(background.checked_at).toLocaleString()}</p>}</div>}
    {trainingMode === 'price_objection' && priceComparison && <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm">
      <h4 className="font-medium text-amber-900">价格资料分别检索</h4>
      <p className="mt-1 text-xs text-amber-800">比较方面：{profile.price_comparison_aspect || '未填写'}。以下只统计已返回的公开来源，具体价格仍需核对原文和日期。</p>
      <ul className="mt-2 space-y-1 text-xs text-gray-700">
        <li>A｜{profile.price_brand_a || '未填写'}：{sourceCount('A品牌价格资料')} 条来源</li>
        <li>B｜{profile.price_brand_b || '未填写'}：{sourceCount('B品牌价格资料')} 条来源</li>
        {profile.price_brand_c && <li>C｜{profile.price_brand_c}：{sourceCount('C品牌价格资料')} 条来源</li>}
        <li>行业市场参考：{sourceCount('市场参考价')} 条来源，仅作参考，不代表 A/B 官方报价</li>
      </ul>
      {priceComparison.organized?.length ? <div className="mt-3 rounded-lg border border-amber-200 bg-white p-3 text-xs">
        <p className="font-semibold text-amber-900">自动整理</p>
        <ul className="mt-1 list-disc space-y-1 pl-5 text-gray-700">{priceComparison.organized.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul>
      </div> : null}
      <div className="mt-3 overflow-hidden rounded-lg border border-amber-200 bg-white">
        <div className="grid grid-cols-[3.5rem_1fr] gap-2 border-b bg-amber-100 px-3 py-2 text-xs font-semibold text-amber-900">
          <span>品牌</span><span>明确价格与来源</span>
        </div>
        {priceComparison.entries.map(entry => <div key={entry.slot} className="grid grid-cols-[3.5rem_1fr] gap-2 border-b px-3 py-2 text-xs last:border-b-0">
          <span className="font-medium">{entry.slot}｜{entry.brand}</span>
          <div className="space-y-1">
            {entry.evidence.length === 0
              ? <p className="text-gray-500">未找到明确金额，需手动核对。</p>
              : entry.evidence.map(item => <p key={`${item.price}-${item.url}-${item.snippet}`}><span className="font-semibold text-amber-800">{item.price}</span>：{item.snippet} {item.url ? <a href={item.url} target="_blank" rel="noreferrer" className="text-primary underline">来源</a> : <span className="text-gray-500">（用户填写，未外部核验）</span>}</p>)}
          </div>
        </div>)}
        <div className="grid grid-cols-[3.5rem_1fr] gap-2 px-3 py-2 text-xs">
          <span className="font-medium">市场</span>
          <div className="space-y-1">
            {priceComparison.market_reference.length === 0
              ? <p className="text-gray-500">未找到有来源的市场参考价，不会自动补造。</p>
              : priceComparison.market_reference.map(item => <p key={`${item.price}-${item.url}`}><span className="font-semibold text-amber-800">{item.price}</span>：{item.snippet} <a href={item.url} target="_blank" rel="noreferrer" className="text-primary underline">来源</a></p>)}
          </div>
        </div>
        <p className="border-t border-amber-100 bg-amber-50 px-3 py-2 text-[11px] text-amber-800">{searching ? '正在补充 A/B 和市场公开来源；当前先显示你填写的比较信息。' : priceComparison.notice}</p>
      </div>
      {background?.gaps?.some(gap => /超时|不可用|失败|重试/.test(gap)) && <button type="button" onClick={() => setSearchRevision(value => value + 1)} className="mt-2 rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-xs font-medium text-amber-800 hover:bg-amber-100">重新检索</button>}
    </div>}
    {!searching && background?.search_key === [profile.organization, profile.product, profile.needs, profile.target].map(value => value.trim()).join('\n') && <SalesMaterialPreview key={JSON.stringify(profile) + trainingMode + background.checked_at} profile={profile} background={background} trainingMode={trainingMode} />}
    </div>
    {profile.product.trim() && profile.target.trim() && <SalesSuggestions key={trainingMode + JSON.stringify(profile)} trainingMode={trainingMode} profile={profile} />}
    <p className="text-xs text-gray-500">{trainingMode === 'price_objection' ? '未填资料保持未知。价格模式中客户会持续关注价格顾虑，不编造报价、优惠或竞品价格。' : '未填资料保持未知。模拟设定：客户沟通谨慎、适度追问，依据你的回应调整态度。'}</p>
    <button type="button" disabled={!ready || starting || searching} onClick={() => void start()} className="w-full rounded-lg bg-primary p-3 font-medium text-white disabled:opacity-40">{!ready ? '请先补充必填信息' : searching ? '正在分别检索 A/B 价格资料…' : starting ? '正在进入对练…' : trainingMode === 'price_objection' ? '价格比较已完整，开始对练' : '直接进入对练'}</button>
    {!ready && <p className="text-sm text-gray-500">还需填写：{missingRequiredLabels.join('、')}。价格模式要求先明确 A/B 品牌、价格比较方面和客户的具体价格顾虑。</p>}
  </section>
}
