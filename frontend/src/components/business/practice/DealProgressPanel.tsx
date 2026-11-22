/**
 * 对练推进看板：阶段进度、必问信息覆盖率、缺口清单、收尾建议。
 *
 * 数据来自 WebSocket 的 `deal_progress` 事件，或 `GET /practice/sessions/{id}/deal-state`。
 * 只做展示，不发起任何判定——判定全部在后端 deal_state 规则里完成。
 */

export interface DealSlot {
  key: string
  label: string
  level: 'required' | 'recommended' | string
  stage: string
  filled: boolean
  value: string | null
}

export interface DealGap {
  key: string
  label: string
  ask: string
  level: string
  stage: string
}

export interface DealProgress {
  template_id?: string
  template_name: string
  stage: string
  stage_label: string
  stage_order: string[]
  stage_labels: Record<string, string>
  coverage: {
    required_total: number
    required_filled: number
    recommended_total: number
    recommended_filled: number
    percent: number
  }
  slots: DealSlot[]
  gaps: DealGap[]
  closing: { suggest: boolean; reason: string | null; result: string | null }
  deal_result: string | null
  round_number: number
}

const resultLabels: Record<string, string> = {
  won: '成交',
  trial: '约了试听',
  lost_explicit: '明确拒绝',
  lost_soft: '考虑中',
  incomplete: '提前终止',
}

const resultTone: Record<string, string> = {
  won: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  trial: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  lost_explicit: 'bg-gray-100 text-gray-600 border-gray-200',
  lost_soft: 'bg-amber-50 text-amber-700 border-amber-200',
  incomplete: 'bg-gray-100 text-gray-500 border-gray-200',
}

interface Props {
  progress: DealProgress | null
  className?: string
}

export default function DealProgressPanel({ progress, className = '' }: Props) {
  if (!progress) return null

  const { coverage, stage_order: order, stage_labels: labels, slots, gaps, closing, deal_result: dealResult } = progress
  const currentIndex = Math.max(order.indexOf(progress.stage), 0)
  const requiredSlots = slots.filter((slot) => slot.level === 'required')
  const filledRequired = requiredSlots.filter((slot) => slot.filled)

  return (
    <div className={`rounded-xl border border-gray-200 bg-white p-3 space-y-3 ${className}`}>
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-gray-500">
          对练推进 · {progress.template_name}
        </p>
        <span className="text-[10px] text-gray-400">第 {progress.round_number} 轮</span>
      </div>

      {/* 阶段进度 */}
      <div className="flex items-center gap-1">
        {order.map((stage, index) => {
          const done = index < currentIndex
          const active = index === currentIndex
          return (
            <div key={stage} className="flex-1">
              <div
                className={`h-1.5 rounded-full transition-colors ${
                  done ? 'bg-blue-400' : active ? 'bg-blue-600' : 'bg-gray-200'
                }`}
              />
              <p
                className={`mt-1 text-[10px] leading-tight ${
                  active ? 'font-medium text-blue-700' : done ? 'text-blue-500' : 'text-gray-400'
                }`}
              >
                {labels[stage] || stage}
              </p>
            </div>
          )
        })}
      </div>

      {/* 覆盖率 */}
      <div className="space-y-1">
        <div className="flex items-baseline justify-between">
          <span className="text-xs text-gray-600">必问信息</span>
          <span className="text-xs font-medium text-gray-800">
            {coverage.required_filled}/{coverage.required_total} · {coverage.percent}%
          </span>
        </div>
        <div className="h-1.5 w-full rounded-full bg-gray-100">
          <div
            className={`h-1.5 rounded-full transition-all ${
              coverage.percent >= 90 ? 'bg-emerald-500' : coverage.percent >= 50 ? 'bg-blue-500' : 'bg-amber-500'
            }`}
            style={{ width: `${coverage.percent}%` }}
          />
        </div>
        {coverage.recommended_total > 0 && (
          <p className="text-[10px] text-gray-400">
            加分项 {coverage.recommended_filled}/{coverage.recommended_total}
          </p>
        )}
      </div>

      {/* 已收集 */}
      {filledRequired.length > 0 && (
        <details className="group">
          <summary className="cursor-pointer list-none text-[11px] text-gray-500 hover:text-gray-700">
            已收集 {filledRequired.length} 项 <span className="text-gray-300">▾</span>
          </summary>
          <ul className="mt-1 space-y-0.5">
            {filledRequired.map((slot) => (
              <li key={slot.key} className="flex gap-1 text-[11px] leading-snug">
                <span className="text-emerald-500">✓</span>
                <span className="text-gray-500">{slot.label}：</span>
                <span className="truncate text-gray-800" title={slot.value || ''}>{slot.value}</span>
              </li>
            ))}
          </ul>
        </details>
      )}

      {/* 待了解 */}
      {gaps.length > 0 && (
        <div>
          <p className="text-[11px] text-gray-500">接下来可以问</p>
          <ul className="mt-1 space-y-1">
            {gaps.map((gap) => (
              <li key={gap.key} className="rounded-lg bg-gray-50 px-2 py-1.5">
                <p className="text-[10px] text-gray-400">
                  {gap.label}
                  {gap.level !== 'required' && <span className="ml-1 text-gray-300">（加分）</span>}
                </p>
                <p className="text-[11px] leading-snug text-gray-700">{gap.ask}</p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 收尾建议 */}
      {closing?.suggest && (
        <div className="rounded-lg border border-blue-200 bg-blue-50 px-2 py-1.5">
          <p className="text-[11px] font-medium text-blue-700">可以尝试收尾了</p>
          {closing.reason && <p className="text-[10px] leading-snug text-blue-600">{closing.reason}</p>}
        </div>
      )}

      {/* 结单结果 */}
      {dealResult && (
        <div className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] ${resultTone[dealResult] || resultTone.incomplete}`}>
          结单：{resultLabels[dealResult] || dealResult}
        </div>
      )}
    </div>
  )
}
