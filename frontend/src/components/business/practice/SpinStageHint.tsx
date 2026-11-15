import { useState } from 'react'

interface Guidance {
  phase: string
  focus: string
  parent_facts: string[]
  unknowns: string[]
  next_step: string
  reminder: string
  script: string
  references: Array<{ source: string; text: string }>
  searched?: boolean
  not_found: boolean
  search_error?: boolean
}

interface Props { guidance: Guidance; className?: string }

const stageName: Record<string, string> = {
  Situation: '现状了解', Problem: '发现困难',
  Implication: '影响探索', 'Need-payoff': '需求与价值',
}

export default function SpinStageHint({ guidance, className = '' }: Props) {
  const [pinned, setPinned] = useState<Guidance['references'][number] | null>(null)
  const currentReference = guidance.references[0] || null
  const shownReference = pinned || currentReference

  return (
    <div className={`space-y-3 ${className}`}>
      <section className="rounded-lg border border-blue-200 bg-blue-50 p-3">
        <div className="mb-1 flex items-center justify-between gap-2">
          <span className="text-xs font-semibold text-blue-700">{stageName[guidance.phase] || guidance.phase}</span>
          <span className="text-[10px] text-blue-600">实时更新</span>
        </div>
        <p className="text-sm font-medium text-gray-900">{guidance.focus}</p>
        <h3 className="mt-3 text-xs font-semibold text-gray-600">家长已表达</h3>
        {guidance.parent_facts.length ? <ul className="mt-1 space-y-1">
          {guidance.parent_facts.map((fact, index) => <li key={index} className="text-xs text-gray-700">• {fact}</li>)}
        </ul> : <p className="mt-1 text-xs text-gray-500">暂未识别到明确的信息</p>}
      </section>

      <section className="rounded-lg border border-gray-200 bg-white p-3">
        <h3 className="text-xs font-semibold text-gray-700">待了解与下一步</h3>
        {guidance.unknowns.length > 0 && <ul className="mt-2 space-y-1">
          {guidance.unknowns.map((item, index) => <li key={index} className="text-xs text-gray-600">• {item}</li>)}
        </ul>}
        <p className="mt-2 rounded bg-gray-50 p-2 text-xs text-gray-700">{guidance.next_step}</p>
      </section>

      <section className="rounded-lg border border-amber-200 bg-amber-50 p-3">
        <h3 className="text-xs font-semibold text-amber-800">实时沟通提醒</h3>
        <p className="mt-1 text-sm text-amber-900">{guidance.reminder}</p>
      </section>

      <section className="rounded-lg border border-gray-200 bg-white p-3">
        <h3 className="text-xs font-semibold text-gray-700">参考资料</h3>
        <p className="mt-2 text-[11px] font-medium text-gray-500">参考话术（AI建议）</p>
        <p className="mt-1 rounded bg-gray-50 p-2 text-xs text-gray-700">“{guidance.script}”</p>
        {shownReference ? <div className="mt-3 rounded border border-gray-200 p-2">
          <div className="flex items-start justify-between gap-2">
            <span className="text-[11px] font-medium text-gray-600">{shownReference.source}{pinned ? ' · 已固定' : ''}</span>
            <button type="button" onClick={() => setPinned(pinned ? null : shownReference)}
              className="shrink-0 text-[11px] text-primary hover:underline">
              {pinned ? '取消固定' : '固定资料'}
            </button>
          </div>
          <p className="mt-1 whitespace-pre-wrap text-xs leading-relaxed text-gray-700">{shownReference.text}</p>
        </div> : guidance.searched && guidance.not_found ? (
          <p className="mt-2 rounded bg-amber-50 p-2 text-xs text-amber-800">知识库未找到相关资料，请勿据此承诺学校、课程、价格或规则信息。</p>
        ) : guidance.searched && guidance.search_error ? (
          <p className="mt-2 rounded bg-amber-50 p-2 text-xs text-amber-800">知识库检索暂不可用，当前无法核实相关信息。</p>
        ) : <p className="mt-2 text-xs text-gray-500">当前主题无需检索资料；涉及学校、课程、价格或规则时会按需查询知识库。</p>}
      </section>
    </div>
  )
}
