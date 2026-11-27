import { useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { organizeFollowUp, type FollowUpProfile } from '../../api/followUps'
import type { PreparationProfile } from '../../components/business/practice/CustomerPreparation'

type TableEntry = { tableId?: string; rowId?: string }
const blank: FollowUpProfile = { customer_name: '', identity: '', product: '', history_summary: '', current_progress: '', expectation: '' }
const fields: Array<[keyof FollowUpProfile, string, string]> = [
  ['customer_name', '客户姓名', '例如：张总'], ['identity', '职务身份', '例如：采购总监'], ['product', '推销产品', '例如：年度设备维护方案'],
  ['history_summary', '历史沟通摘要', '已沟通内容、需求、顾虑或约定'], ['current_progress', '当前进度', '例如：预算审批中，等待确认演示时间'], ['expectation', '回访预期', '例如：确认预算进度并约定下周演示'],
]

export default function FollowUpPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const entry = (location.state || {}) as TableEntry
  const [description, setDescription] = useState('')
  const [profile, setProfile] = useState<FollowUpProfile>(blank)
  const [scripts, setScripts] = useState<string[]>([])
  const [isOrganizing, setIsOrganizing] = useState(false)
  const [error, setError] = useState('')
  const hasDraft = useMemo(() => Object.values(profile).some(Boolean), [profile])

  const organize = async () => {
    if (!description.trim() && !entry.rowId) { setError('请描述客户情况，或从客户列表选择一位客户。'); return }
    setIsOrganizing(true); setError('')
    try {
      const draft = await organizeFollowUp({ description, table_id: entry.tableId, row_id: entry.rowId })
      setProfile(draft.profile); setScripts(draft.scripts)
    } catch (requestError: any) { setError(requestError?.response?.data?.detail || '整理暂时失败，请稍后重试。') }
    finally { setIsOrganizing(false) }
  }
  const update = (key: keyof FollowUpProfile, value: string) => setProfile(current => ({ ...current, [key]: value }))
  const continueToPractice = () => {
    const preparation: Partial<PreparationProfile> = {
      product: profile.product, target: profile.identity, organization: profile.customer_name,
      needs: [profile.history_summary, profile.current_progress].filter(Boolean).join('；'), preferences: profile.current_progress, goal: profile.expectation,
    }
    navigate('/practice', { state: {
      customerContext: { training_mode: 'full', industry: '', scale: '', pain_points: preparation.needs ? [preparation.needs] : [], preparation, follow_up: true },
      investigationResult: { name: profile.customer_name, title: profile.identity, background: profile.history_summary, potential_pains: profile.current_progress ? [profile.current_progress] : [] },
      userContext: { follow_up: true, follow_up_profile: profile },
    } })
  }

  return <main className="mx-auto max-w-5xl px-4 py-8">
    <div className="mb-8 flex items-start justify-between gap-4"><div><p className="text-sm font-medium text-primary">客户经营</p><h1 className="mt-1 text-3xl font-bold text-gray-900">回访与跟进</h1><p className="mt-2 text-gray-600">输入客户情况，AI 会整理回访重点、准备资料，并进入模拟对练。</p></div><button type="button" onClick={() => navigate('/customers')} className="shrink-0 rounded-lg border border-primary px-4 py-2 text-sm font-medium text-primary hover:bg-blue-50">客户列表 →</button></div>
    <section className="rounded-2xl border border-blue-100 bg-white p-5 shadow-sm"><label className="block text-lg font-semibold text-gray-900">描述客户特征或本次回访情况</label><p className="mt-1 text-sm text-gray-500">知道多少写多少。例如：张总上周看过方案，预算还未确定，想约下周演示。</p><textarea value={description} onChange={event => setDescription(event.target.value)} maxLength={5000} rows={6} placeholder="请输入客户情况、历史沟通和本次想推进的目标…" className="mt-4 w-full rounded-xl border border-gray-300 p-4 text-base outline-none focus:border-primary focus:ring-2 focus:ring-primary/20" /><button type="button" onClick={() => void organize()} disabled={isOrganizing} className="mt-4 rounded-lg bg-primary px-5 py-3 font-medium text-white hover:bg-blue-700 disabled:opacity-50">{isOrganizing ? 'AI 正在整理…' : entry.rowId ? '整理客户回访信息' : 'AI 整理客户信息'}</button>{error && <p role="alert" className="mt-3 text-sm text-red-600">{error}</p>}</section>
    {hasDraft && <section className="mt-6 grid gap-6 lg:grid-cols-[1fr_18rem]"><div className="rounded-2xl border bg-white shadow-sm"><div className="border-b px-5 py-4"><h2 className="font-semibold text-gray-900">客户回访档案</h2><p className="mt-1 text-sm text-gray-500">可直接修改；修改后的内容会用于资料准备和模拟对练。</p></div><div className="divide-y">{fields.map(([key, label, placeholder]) => <label key={key} className="block p-4 sm:grid sm:grid-cols-[9rem_1fr] sm:gap-4"><span className="mb-2 block text-sm font-medium text-gray-700 sm:mb-0">{label}</span>{key === 'history_summary' || key === 'current_progress' || key === 'expectation' ? <textarea rows={3} value={profile[key]} onChange={event => update(key, event.target.value)} placeholder={placeholder} className="w-full rounded-lg border px-3 py-2 text-sm" /> : <input value={profile[key]} onChange={event => update(key, event.target.value)} placeholder={placeholder} className="w-full rounded-lg border px-3 py-2 text-sm" />}</label>)}</div></div><aside className="space-y-4"><div className="rounded-2xl border border-blue-100 bg-blue-50 p-4"><h2 className="font-semibold text-blue-950">本次回访重点</h2><p className="mt-2 text-sm leading-6 text-blue-900">{profile.customer_name || '客户'}{profile.current_progress ? `当前处于“${profile.current_progress}”` : '的当前情况需要进一步确认'}；本次优先{profile.expectation || '确认下一步安排'}。</p></div><div className="rounded-2xl border bg-white p-4"><h2 className="font-semibold text-gray-900">回访话术</h2><div className="mt-3 space-y-2">{scripts.map(script => <button key={script} type="button" onClick={() => setDescription(current => current ? `${current}\n${script}` : script)} className="w-full rounded-xl border border-blue-100 bg-blue-50 p-3 text-left text-sm text-blue-900 hover:bg-blue-100">{script}</button>)}</div></div></aside><div className="lg:col-span-2 rounded-2xl border border-amber-200 bg-amber-50 p-5"><h2 className="font-semibold text-amber-950">资料准备与模拟对练</h2><p className="mt-2 text-sm text-amber-900">继续后将使用现有资料搜索、信息简报/PDF 和销售建议能力，并以这份回访档案创建模拟对练。</p><button type="button" onClick={continueToPractice} disabled={!profile.product || !profile.expectation} className="mt-4 rounded-lg bg-primary px-5 py-3 font-medium text-white disabled:opacity-50">继续准备并开始回访对练 →</button></div></section>}
  </main>
}
