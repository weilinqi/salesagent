import PracticeMaterialsPanel from './PracticeMaterialsPanel'
import type { Background, PreparationProfile } from './CustomerPreparation'

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
  isInitial?: boolean
  last_search_query?: string
  updated_at?: string
}

interface Props {
  guidance: Guidance
  className?: string
  sessionId?: string
  preparationProfile?: PreparationProfile
  preparationBackground?: Background
}

const stageName: Record<string, string> = {
  Situation: '现状了解', Problem: '发现困难',
  Implication: '影响探索', 'Need-payoff': '需求与价值',
}

export default function SpinStageHint({ guidance, className = '', sessionId, preparationProfile, preparationBackground }: Props) {
  return (
    <div className={`space-y-3 ${className}`}>
      <section className="rounded-lg border border-blue-200 bg-blue-50 p-3">
        <div className="mb-1 flex items-center justify-between gap-2">
          <span className="text-xs font-semibold text-blue-700">{stageName[guidance.phase] || guidance.phase}</span>
          <span className="text-[10px] text-blue-600">{guidance.isInitial ? '开场提示' : '实时更新'}</span>
        </div>
        <p className="text-sm font-medium text-gray-900">{guidance.focus}</p>
        <h3 className="mt-3 text-xs font-semibold text-gray-600">家长已表达</h3>
        {guidance.parent_facts.length ? <ul className="mt-1 space-y-1">
          {guidance.parent_facts.map((fact, index) => <li key={index} className="text-xs text-gray-700">• {fact}</li>)}
        </ul> : <p className="mt-1 text-xs text-gray-500">对话开始后记录家长明确表达的信息</p>}
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

      <section className="space-y-2">
        <div className="rounded-lg border border-gray-200 bg-white p-3">
          <h3 className="text-xs font-semibold text-gray-700">参考话术（AI建议）</h3>
          <p className="mt-1 rounded bg-gray-50 p-2 text-xs text-gray-700">“{guidance.script}”</p>
        </div>
        <PracticeMaterialsPanel
          sessionId={sessionId}
          profile={preparationProfile}
          background={preparationBackground}
          references={guidance.references}
          searched={guidance.searched}
          notFound={guidance.not_found}
          searchError={guidance.search_error}
          searchQuery={guidance.last_search_query}
          updatedAt={guidance.updated_at}
        />
      </section>
    </div>
  )
}
