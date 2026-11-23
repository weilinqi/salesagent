/**
 * 对练右侧栏 · 三段式
 *
 * 设计原则（见《对练侧边栏优化方案》）：
 * 1. 同一时刻只有一张"行动卡"——合并「接下来可以问」与「下一步/话术」
 * 2. 状态信息折叠成一行——阶段点 + 覆盖率，想看细节再展开
 * 3. 备查资料全部折叠——必问清单 / 家长已表达 / 知识库引用
 * 4. 事件卡（里程碑）出现时插到最上方，处理完自动收起
 */

import { useMemo, useState, type ReactNode } from 'react'

import type { DealProgress } from './DealProgressPanel'

export interface PracticeGuidance {
  phase: string
  focus: string
  parent_facts: string[]
  unknowns: string[]
  next_step: string
  reminder: string
  script: string
  references: Array<{ source: string; text: string }>
  not_found: boolean
  searched?: boolean
  search_error?: boolean
  isInitial?: boolean
  round_number?: number
  last_search_query?: string
  updated_at?: string
}

/** 里程碑事件卡：现在还没有数据源，先把位置和交互留出来 */
export interface PendingEvent {
  title: string
  description?: string
  actions: Array<{ label: string; onClick: () => void; tone?: 'primary' | 'neutral' | 'danger' }>
  onDismiss?: () => void
}

interface Props {
  deal: DealProgress | null
  guidance: PracticeGuidance | null
  /** 「资料」按钮等由页面传入，避免这里依赖知识库组件 */
  materials?: ReactNode
  status?: 'updating' | 'updated' | 'error' | null
  statusError?: string | null
  statusDurationMs?: number | null
  /** 待办事件卡（里程碑功能接入后填充） */
  pendingEvent?: PendingEvent | null
  /** 撤销入口：点错了可以把里程碑改回"未完成" */
  undoAction?: { label: string; onClick: () => void } | null
  collapsed: boolean
  onToggleCollapse: () => void
  className?: string
}

const CLOSE_HEADLINES: Record<string, string> = {
  won: '已经谈成了，可以结束对练',
  lost_explicit: '家长已明确拒绝，可以结束对练',
  lost_soft: '家长还在犹豫，可以结束并记录跟进',
}

const CLOSE_TONES: Record<string, string> = {
  won: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  lost_explicit: 'border-gray-200 bg-gray-50 text-gray-700',
  lost_soft: 'border-amber-200 bg-amber-50 text-amber-800',
}

function SectionToggle({
  open, label, onClick,
}: { open: boolean; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center justify-between rounded-lg border border-gray-200 bg-white px-2.5 py-2 text-left text-[11px] text-gray-600 transition-colors hover:bg-gray-50"
    >
      <span className="truncate">{label}</span>
      <span className="ml-2 shrink-0 text-gray-400">{open ? '▾' : '▸'}</span>
    </button>
  )
}

export default function PracticeSidebar({
  deal, guidance, materials, status, statusError, statusDurationMs,
  pendingEvent, undoAction, collapsed, onToggleCollapse, className = '',
}: Props) {
  const [openSection, setOpenSection] = useState<'gaps' | 'facts' | 'refs' | null>(null)
  const [showProgressDetail, setShowProgressDetail] = useState(false)

  const closingResult = deal?.closing?.result || null
  const closingReady = Boolean(
    deal?.closing?.suggest && closingResult && CLOSE_HEADLINES[closingResult],
  )

  const stages = deal?.stage_order || []
  const stageLabels = deal?.stage_labels || {}
  const currentStageIndex = deal ? Math.max(stages.indexOf(deal.stage), 0) : -1
  const stageLabel = deal ? (stageLabels[deal.stage] || deal.stage) : (guidance?.phase || '')

  const gap = deal?.gaps?.[0]

  // 行动卡内容：结束建议 > 必填缺口 > SPIN 下一步
  const focus = useMemo(() => {
    if (closingReady && closingResult) {
      return {
        tone: 'closing' as const,
        title: CLOSE_HEADLINES[closingResult],
        script: '',
        hint: deal?.closing?.reason || '',
      }
    }
    if (gap) {
      return {
        tone: 'gap' as const,
        title: `先问出「${gap.label}」`,
        script: gap.ask,
        hint: guidance?.next_step && guidance.next_step !== gap.ask ? `策略：${guidance.next_step}` : '',
      }
    }
    return {
      tone: 'spin' as const,
      title: guidance?.next_step || '用开放问题了解家长最关心的目标',
      script: guidance?.script || '',
      hint: guidance?.focus || '',
    }
  }, [closingReady, closingResult, deal?.closing?.reason, gap, guidance?.next_step, guidance?.script, guidance?.focus])

  const pendingSlots = deal?.slots?.filter((slot) => !slot.filled) || []
  const filledFacts = deal?.slots?.filter((slot) => slot.filled).map((slot) => `${slot.label}：${slot.value}`) || []
  const parentFacts = useMemo(() => {
    const merged = [...filledFacts, ...(guidance?.parent_facts || [])]
    return Array.from(new Set(merged.map((item) => item.trim()))).filter(Boolean)
  }, [filledFacts, guidance?.parent_facts])
  const references = guidance?.references || []

  const coverage = deal?.coverage
  const statusLabel = status === 'updating'
    ? '正在更新…'
    : status === 'error'
      ? `更新失败${statusError ? `（${statusError}）` : ''}`
      : statusDurationMs != null
        ? `${statusDurationMs < 1000 ? `${statusDurationMs} 毫秒` : `${(statusDurationMs / 1000).toFixed(1)} 秒`}`
        : ''

  if (collapsed) {
    return (
      <aside className={`flex w-9 shrink-0 flex-col items-center gap-3 border-l border-gray-200 bg-gray-50 py-3 ${className}`}>
        <button
          type="button"
          onClick={onToggleCollapse}
          title="展开侧栏"
          className="rounded-md px-1 py-1 text-gray-500 transition-colors hover:bg-white hover:text-gray-700"
        >
          «
        </button>
        <span className="text-[11px] leading-tight text-gray-500 [writing-mode:vertical-rl]">实时指导</span>
      </aside>
    )
  }

  return (
    <aside className={`flex w-80 shrink-0 flex-col gap-2 overflow-y-auto border-l border-gray-200 bg-gray-50 p-3 ${className}`}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium text-gray-500">实时指导</p>
        <div className="flex items-center gap-1">
          {materials}
          <button
            type="button"
            onClick={onToggleCollapse}
            title="收起侧栏"
            className="rounded-md px-1.5 py-1 text-xs text-gray-400 transition-colors hover:bg-white hover:text-gray-600"
          >
            »
          </button>
        </div>
      </div>

      {/* ④ 事件卡：有数据时插到最上方，优先级最高 */}
      {pendingEvent && (
        <section className="rounded-xl border-2 border-amber-300 bg-amber-50 p-3">
          <p className="text-xs font-semibold text-amber-800">⏰ {pendingEvent.title}</p>
          {pendingEvent.description && (
            <p className="mt-1 text-[11px] leading-snug text-amber-700">{pendingEvent.description}</p>
          )}
          <div className="mt-2 flex flex-wrap gap-1.5">
            {pendingEvent.actions.map((action) => (
              <button
                key={action.label}
                type="button"
                onClick={action.onClick}
                className={`rounded-md px-2 py-1 text-[11px] font-medium text-white transition-colors ${
                  action.tone === 'neutral' ? 'bg-gray-500 hover:bg-gray-600'
                    : action.tone === 'danger' ? 'bg-rose-600 hover:bg-rose-700'
                      : 'bg-emerald-600 hover:bg-emerald-700'
                }`}
              >
                {action.label}
              </button>
            ))}
          </div>
          {pendingEvent.onDismiss && (
            <button
              type="button"
              onClick={pendingEvent.onDismiss}
              className="mt-2 text-[10px] text-amber-700 underline-offset-2 hover:underline"
            >
              稍后再说
            </button>
          )}
        </section>
      )}

      {/* ① 焦点卡：只有一张 */}
      <section className={`rounded-xl border p-3 ${
        focus.tone === 'closing'
          ? (CLOSE_TONES[closingResult || ''] || 'border-gray-200 bg-gray-50 text-gray-700')
          : 'border-blue-200 bg-white'
      }`}>
        <div className="flex items-center justify-between">
          <p className={`text-[10px] font-semibold ${focus.tone === 'closing' ? '' : 'text-blue-600'}`}>
            ⭐ 这一句说什么
          </p>
          {statusLabel && (
            <span className={`text-[10px] ${status === 'error' ? 'text-amber-600' : 'text-gray-400'}`}>
              {statusLabel}
            </span>
          )}
        </div>
        <p className="mt-1.5 text-sm font-medium leading-snug text-gray-900">{focus.title}</p>
        {focus.script && (
          <p className="mt-2 rounded-lg bg-blue-50 px-2 py-1.5 text-[12px] leading-snug text-blue-900">
            “{focus.script}”
          </p>
        )}
        {focus.hint && (
          <p className="mt-1.5 text-[10px] leading-snug text-gray-500">{focus.hint}</p>
        )}
        {guidance?.reminder && focus.tone !== 'closing' && (
          <p className="mt-1.5 text-[10px] leading-snug text-amber-600">⚠ {guidance.reminder}</p>
        )}
        {deal?.trial_agreed && !closingReady && (
          <p className="mt-2 rounded-md bg-blue-50 px-2 py-1 text-[10px] leading-snug text-blue-700">
            已约试听 · 继续推动报名
          </p>
        )}
      </section>

      {/* ② 进度：一行 */}
      <section className="rounded-xl border border-gray-200 bg-white px-2.5 py-2">
        <button
          type="button"
          onClick={() => setShowProgressDetail((value) => !value)}
          className="flex w-full items-center gap-2 text-left"
        >
          <span className="flex shrink-0 items-center gap-[3px]">
            {stages.map((stage, index) => (
              <span
                key={stage}
                className={`h-1.5 w-1.5 rounded-full ${
                  index < currentStageIndex ? 'bg-blue-300'
                    : index === currentStageIndex ? 'bg-blue-600'
                      : 'bg-gray-200'
                }`}
              />
            ))}
          </span>
          <span className="min-w-0 flex-1 truncate text-[11px] text-gray-700">
            {stageLabel}
            {coverage && ` · 必问 ${coverage.required_filled}/${coverage.required_total}`}
          </span>
          <span className="shrink-0 text-[10px] text-gray-400">{showProgressDetail ? '收起 ▴' : '展开 ▾'}</span>
        </button>
        {showProgressDetail && (
          <div className="mt-2 space-y-1.5 border-t border-gray-100 pt-2">
            <div className="flex flex-wrap gap-x-2 gap-y-0.5">
              {stages.map((stage, index) => (
                <span
                  key={stage}
                  className={`text-[10px] ${
                    index === currentStageIndex ? 'font-medium text-blue-700'
                      : index < currentStageIndex ? 'text-blue-500' : 'text-gray-400'
                  }`}
                >
                  {stageLabels[stage] || stage}
                </span>
              ))}
            </div>
            {coverage && (
              <>
                <div className="h-1.5 w-full rounded-full bg-gray-100">
                  <div
                    className={`h-1.5 rounded-full ${
                      coverage.percent >= 90 ? 'bg-emerald-500' : coverage.percent >= 50 ? 'bg-blue-500' : 'bg-amber-500'
                    }`}
                    style={{ width: `${coverage.percent}%` }}
                  />
                </div>
                <p className="text-[10px] text-gray-400">
                  覆盖率 {coverage.percent}% · 加分项 {coverage.recommended_filled}/{coverage.recommended_total}
                </p>
              </>
            )}
          </div>
        )}
      </section>

      {/* ③ 折叠区：备查 */}
      <div className="space-y-1.5">
        <SectionToggle
          open={openSection === 'gaps'}
          label={`必问清单（还差 ${pendingSlots.length} 项）`}
          onClick={() => setOpenSection(openSection === 'gaps' ? null : 'gaps')}
        />
        {openSection === 'gaps' && (
          <div className="space-y-1 rounded-lg bg-white p-2">
            {pendingSlots.length === 0 && <p className="text-[11px] text-gray-400">必问项已全部收集</p>}
            {pendingSlots.map((slot) => (
              <div key={slot.key} className="rounded-md bg-gray-50 px-2 py-1.5">
                <p className="text-[10px] text-gray-400">
                  {slot.label}
                  {slot.level !== 'required' && <span className="ml-1 text-gray-300">（加分）</span>}
                </p>
                <p className="text-[11px] leading-snug text-gray-700">
                  {deal?.gaps.find((item) => item.key === slot.key)?.ask || slot.label}
                </p>
              </div>
            ))}
          </div>
        )}

        <SectionToggle
          open={openSection === 'facts'}
          label={`家长已表达（${parentFacts.length} 条）`}
          onClick={() => setOpenSection(openSection === 'facts' ? null : 'facts')}
        />
        {openSection === 'facts' && (
          <div className="rounded-lg bg-white p-2">
            {parentFacts.length === 0
              ? <p className="text-[11px] text-gray-400">对话开始后这里会记录家长明确表达的信息</p>
              : (
                <ul className="space-y-1">
                  {parentFacts.map((fact) => (
                    <li key={fact} className="text-[11px] leading-snug text-gray-700">• {fact}</li>
                  ))}
                </ul>
              )}
          </div>
        )}

        <SectionToggle
          open={openSection === 'refs'}
          label={`知识库引用（${references.length} 条）`}
          onClick={() => setOpenSection(openSection === 'refs' ? null : 'refs')}
        />
        {openSection === 'refs' && (
          <div className="space-y-1 rounded-lg bg-white p-2">
            {references.length === 0
              ? (
                <p className="text-[11px] text-gray-400">
                  {guidance?.not_found ? '知识库未找到相关资料' : '本轮暂未引用知识库'}
                </p>
              )
              : references.map((reference, index) => (
                <div key={`${reference.source}-${index}`} className="rounded-md bg-gray-50 px-2 py-1.5">
                  <p className="text-[10px] text-gray-400">{reference.source}</p>
                  <p className="text-[11px] leading-snug text-gray-700">{reference.text.slice(0, 120)}</p>
                </div>
              ))}
          </div>
        )}
      </div>

      {undoAction && (
        <button
          type="button"
          onClick={undoAction.onClick}
          className="self-start text-[10px] text-gray-400 underline-offset-2 transition-colors hover:text-gray-600 hover:underline"
        >
          {undoAction.label}
        </button>
      )}
    </aside>
  )
}
