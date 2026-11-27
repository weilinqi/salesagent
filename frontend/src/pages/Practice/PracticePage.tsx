/**
 * PracticePage - 场景选择与配置页面
 *
 * Flow:
 * 1. 场景选择 -> 2. 介绍推销对象 -> 3. 开始对练
 *
 * Story: 1.1 场景选择与配置
 */
import { useEffect, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { usePracticeStore } from '../../stores/practiceStore'
import { useSpinStore } from '../../stores/spinStore'
import { useAuth } from '../../contexts/AuthContext'
import { RoleConfig, PracticeSessionContext } from '../../api/practice'
import practiceApi from '../../api/practice'
import { organizeFollowUp } from '../../api/followUps'

import VoiceSelector, { VOICE_OPTIONS } from '../../components/business/practice/VoiceSelector'
import CustomerPreparation, { PreparationProfile, Background } from '../../components/business/practice/CustomerPreparation'

type Step = 'select' | 'configure' | 'ready'
type PracticeProfileHistoryEntry = {
  id: string
  createdAt: string
  trainingMode: 'full' | 'rejection' | 'price_objection' | 'follow_up'
  profile: PreparationProfile
}

const PROFILE_HISTORY_LIMIT = 20

function profileHistoryKey(userId?: string) {
  return `sales-agent-practice-profile-history:${userId || 'anonymous'}`
}

function readProfileHistory(userId?: string): PracticeProfileHistoryEntry[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(profileHistoryKey(userId)) || '[]')
    if (!Array.isArray(value)) return []
    return value.filter((entry): entry is PracticeProfileHistoryEntry =>
      entry && typeof entry === 'object' &&
      typeof entry.id === 'string' && typeof entry.createdAt === 'string' && !Number.isNaN(Date.parse(entry.createdAt)) &&
      (entry.trainingMode === 'full' || entry.trainingMode === 'rejection' || entry.trainingMode === 'price_objection' || entry.trainingMode === 'follow_up') &&
      entry.profile && typeof entry.profile === 'object' &&
      ['industry', 'product', 'target', 'organization', 'needs', 'preferences', 'goal']
        .every(key => typeof entry.profile[key as keyof PreparationProfile] === 'string')
    ).slice(0, PROFILE_HISTORY_LIMIT)
  } catch {
    return []
  }
}

function saveProfileHistory(userId: string | undefined, profile: PreparationProfile, trainingMode: 'full' | 'rejection' | 'price_objection' | 'follow_up') {
  const entry: PracticeProfileHistoryEntry = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    createdAt: new Date().toISOString(),
    trainingMode,
    profile,
  }
  const history = [entry, ...readProfileHistory(userId)].slice(0, PROFILE_HISTORY_LIMIT)
  try {
    localStorage.setItem(profileHistoryKey(userId), JSON.stringify(history))
  } catch {
    // Saving history is optional; it must not block a practice session.
  }
  return history
}

const PracticePage = () => {
  const navigate = useNavigate()
  const location = useLocation()
  const spin = useSpinStore()
  const previous: PracticeSessionContext = (location.state as PracticeSessionContext | null) || {
    customerContext: spin.customerContext || undefined,
    investigationResult: spin.investigationResult || undefined,
  }
  const initialProfile: Partial<PreparationProfile> = {
    ...(previous?.customerContext?.preparation || {}),
    industry: previous?.customerContext?.industry || previous?.customerContext?.preparation?.industry || '',
    target: previous?.investigationResult?.title || previous?.investigationResult?.name || previous?.customerContext?.preparation?.target || '',
    organization: previous?.investigationResult?.company || previous?.customerContext?.preparation?.organization || '',
    needs: previous?.customerContext?.pain_points?.join('；') || previous?.customerContext?.preparation?.needs || '',
  }
  const source = (previous?.userContext?.follow_up_source || {}) as { tableId?: string; rowId?: string }
  const isFollowUp = previous?.customerContext?.training_mode === 'follow_up' || Boolean(previous?.customerContext?.follow_up || previous?.userContext?.follow_up || source.rowId)
  const { user } = useAuth()
  const {
    scenarios,
    selectedRoleConfig,
    isLoadingScenarios,
    scenarioError,
    fetchScenarios,
    selectScenario,
    setRoleConfig,
    startSession,
    resetSession
  } = usePracticeStore()

  const [trainingMode, setTrainingMode] = useState<'full' | 'rejection' | 'price_objection' | 'follow_up'>(isFollowUp ? 'follow_up' : 'full')
  const [draft, setDraft] = useState<Partial<PreparationProfile>>(initialProfile)
  const [profileHistory, setProfileHistory] = useState<PracticeProfileHistoryEntry[]>([])
  const [showProfileHistory, setShowProfileHistory] = useState(false)
  const [showVoiceSelector, setShowVoiceSelector] = useState(false)
  const [preparationRevision, setPreparationRevision] = useState(0)
  const moduleTitle = trainingMode === 'follow_up' ? '回访与跟进' : trainingMode === 'rejection' ? '拒绝挽回' : trainingMode === 'price_objection' ? '价格异议处理' : '完整销售对练'
  const [currentStep, setCurrentStep] = useState<Step>('select')
  const [isStarting, setIsStarting] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)

  useEffect(() => {
    fetchScenarios()
  }, [fetchScenarios])

  useEffect(() => {
    setProfileHistory(readProfileHistory(user?.id))
    setShowProfileHistory(false)
  }, [user?.id])

  // Navigate to chat page when session is ready
  useEffect(() => {
    if (currentStep === 'ready' && selectedRoleConfig) {
      navigate('/practice/chat')
    }
  }, [currentStep, selectedRoleConfig, navigate])

  const chooseModule = (mode: 'full' | 'rejection' | 'price_objection' | 'follow_up') => {
    const template = scenarios[0]
    if (!template) return
    resetSession()
    setTrainingMode(mode)
    selectScenario(template)
    setCurrentStep('configure')
    setStartError(null)
  }

  useEffect(() => {
    if (isFollowUp && currentStep === 'select' && scenarios.length > 0) chooseModule('follow_up')
  }, [isFollowUp, currentStep, scenarios.length])

  useEffect(() => {
    if (!source.tableId || !source.rowId) return
    let active = true
    organizeFollowUp({ table_id: source.tableId, row_id: source.rowId })
      .then(({ profile }) => {
        if (!active) return
        setDraft(current => ({ ...current,
          customer_name: profile.customer_name,
          target: profile.identity,
          product: profile.product,
          history_summary: profile.history_summary,
          current_progress: profile.current_progress,
          follow_up_expectation: profile.expectation,
        }))
        setPreparationRevision(value => value + 1)
      })
      .catch(() => setStartError('客户信息整理失败，请直接补充下方信息后重试。'))
    return () => { active = false }
  }, [source.tableId, source.rowId])

  const handleRoleConfigChange = (config: RoleConfig) => {
    setRoleConfig(config)
  }

  const handleVoiceChange = (voice: string) => {
    handleRoleConfigChange({
      position_level: selectedRoleConfig?.position_level || 'middle',
      personality: selectedRoleConfig?.personality || 'rational',
      decision_style: selectedRoleConfig?.decision_style || 'value_oriented',
      voice,
    })
    setShowVoiceSelector(false)
  }

  const startPractice = async (profile: PreparationProfile, background?: Background) => {
    setIsStarting(true)
    setStartError(null)
    try {
      if (!selectedRoleConfig) setRoleConfig({ position_level: 'middle', personality: 'rational', decision_style: 'value_oriented', voice: 'male-qn-qingse' })
      await startSession({
        customerContext: { training_mode: trainingMode, follow_up: trainingMode === 'follow_up', industry: profile.industry, scale: '', pain_points: profile.needs ? [profile.needs] : [], preparation: profile, preparation_background: background },
        investigationResult: previous?.investigationResult,
        userContext: { ...(previous?.userContext || {}), sales_name: user?.full_name || user?.username || '销售员', practice_goals: [profile.goal] },
      })
      if (background?.search_key) {
        const session = usePracticeStore.getState().currentSession
        if (!session) throw new Error('对练会话创建后未能读取会话信息')
        try {
          await practiceApi.saveSessionPreparationPdf(session.id, profile, background, trainingMode)
        } catch (error) {
          await usePracticeStore.getState().endSession()
          throw new Error(error instanceof Error ? `对话前 PDF 保存失败：${error.message}` : '对话前 PDF 保存失败，请重试')
        }
      }
      setProfileHistory(saveProfileHistory(user?.id, profile, trainingMode))
      setCurrentStep('ready')
    } catch (error) {
      setStartError(error instanceof Error ? error.message : '启动对练失败')
    } finally { setIsStarting(false) }
  }

  const handleReset = () => {
    resetSession()
    setCurrentStep('select')
    setStartError(null)
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-sm">
        <div className="max-w-4xl mx-auto px-4 py-4">
          <h1 className="text-2xl font-bold text-gray-900">销售对练</h1>
          <p className="text-sm text-gray-500 mt-1">与AI客户进行实时销售演练</p>
        </div>
      </header>

      {/* Progress Steps */}
      <div className="max-w-4xl mx-auto px-4 py-6">
        <div className="flex items-center justify-center gap-4">
          <StepIndicator number={1} label="选择训练模块" active={currentStep === 'select'} completed={currentStep !== 'select'} />
          <div className={`w-12 h-0.5 ${currentStep !== 'select' ? 'bg-primary' : 'bg-gray-300'}`} />
          <StepIndicator number={2} label="介绍推销对象" active={currentStep === 'configure'} completed={currentStep === 'ready'} />
          <div className={`w-12 h-0.5 ${currentStep === 'ready' ? 'bg-primary' : 'bg-gray-300'}`} />
          <StepIndicator number={3} label="开始对练" active={currentStep === 'ready'} completed={false} />
        </div>
      </div>

      {/* Main Content */}
      <main className="max-w-4xl mx-auto px-4 pb-8">
        {/* Error Display */}
        {(scenarioError || startError) && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-red-700">{scenarioError || startError}</p>
          </div>
        )}

        {/* Step 1: Scenario Selection */}
        {currentStep === 'select' && (
          <div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-gray-900">选择训练模块</h2>
              <span className="text-sm text-gray-500">4 个训练模块</span>
            </div>

            {isLoadingScenarios ? (
              <div className="grid gap-4 md:grid-cols-2">
                {[1, 2, 3, 4].map(i => (
                  <div key={i} className="animate-pulse p-4 rounded-lg border-2 border-gray-200 bg-gray-100 h-32" />
                ))}
              </div>
            ) : scenarios.length === 0 ? (
              <div className="text-center py-12 bg-white rounded-lg border border-gray-200">
                <p className="text-gray-500">暂无可用场景</p>
              </div>
            ) : (
              <div className="grid gap-4 md:grid-cols-2">
                {([{ mode: 'full', name: '完整销售对练', description: '从初次接触到推进下一步，练习完整销售沟通。' }, { mode: 'rejection', name: '拒绝挽回', description: '从客户拒绝开始，练习了解顾虑、回应异议和争取后续机会。' }, { mode: 'price_objection', name: '价格异议处理', description: '从客户提出价格顾虑开始，练习问清和什么相比、拆解价值并推进下一步。' }, { mode: 'follow_up', name: '回访与跟进', description: '从既有客户沟通记录出发，练习确认进度、处理顾虑并约定下一步。' }] as const).map(module => (
                  <button type="button" key={module.mode} onClick={() => chooseModule(module.mode)} className="rounded-xl border-2 border-blue-100 bg-white p-6 text-left shadow-sm transition hover:border-blue-600 hover:bg-blue-50 focus-visible:outline-blue-600">
                    <h3 className="text-xl font-semibold text-blue-800">{module.name}</h3>
                    <p className="mt-3 text-sm leading-relaxed text-gray-600">{module.description}</p>
                    <span className="mt-5 block text-sm font-medium text-blue-600">开始准备 →</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Step 2: Role Configuration */}
        {currentStep === 'configure' && (
          <div className="bg-white rounded-xl shadow-sm p-6">
            <div className="mb-6">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-gray-900">准备针对性对练</h2>
                  <p className="text-sm text-gray-500 mt-1">
                    当前模块: <span className="font-medium text-primary">{moduleTitle}</span>
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => navigate('/customers')}
                    className="rounded-lg bg-cyan-500 px-5 py-2.5 text-base font-semibold text-white shadow-sm hover:bg-cyan-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-700"
                  >
                    客户列表
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowVoiceSelector(true)}
                    className="rounded-lg bg-violet-600 px-5 py-2.5 text-base font-semibold text-white shadow-sm hover:bg-violet-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-700"
                  >
                    AI 声线选择：{VOICE_OPTIONS.find(item => item.id === (selectedRoleConfig?.voice || 'male-qn-qingse'))?.name || '默认男声'}
                  </button>
                  <button
                    type="button"
                    aria-expanded={showProfileHistory}
                    aria-controls="practice-profile-history"
                    onClick={() => setShowProfileHistory(value => !value)}
                    className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
                  >
                    历史填写
                  </button>
                  <button
                    onClick={() => {
                      resetSession()
                      setCurrentStep('select')
                    }}
                    className="text-sm text-gray-500 hover:text-gray-700"
                  >
                    返回选择模块
                  </button>
                </div>
              </div>
              {showProfileHistory && (
                <div id="practice-profile-history" className="mt-4 rounded-lg border border-blue-100 bg-blue-50/50 p-4" aria-label="历史填写记录">
                  <h3 className="mb-3 text-sm font-semibold text-gray-800">历史填写</h3>
                  {profileHistory.length === 0 ? (
                    <p className="text-sm text-gray-500">还没有成功开始过的对练记录。</p>
                  ) : (
                    <ul className="space-y-2">
                      {profileHistory.map(entry => (
                        <li key={entry.id} className="flex flex-col gap-3 rounded-lg border bg-white p-3 sm:flex-row sm:items-center sm:justify-between">
                          <div className="min-w-0">
                            <p className="truncate text-sm font-medium text-gray-900">
                              {entry.profile.organization || entry.profile.target || entry.profile.product || '未命名对象'}
                            </p>
                            <p className="mt-1 truncate text-xs text-gray-600">
                              {entry.trainingMode === 'follow_up' ? '回访与跟进' : entry.trainingMode === 'rejection' ? '拒绝挽回' : entry.trainingMode === 'price_objection' ? '价格异议处理' : '完整销售对练'} · {entry.profile.target || entry.profile.product}
                            </p>
                            <p className="mt-1 text-xs text-gray-400">{new Date(entry.createdAt).toLocaleString()}</p>
                          </div>
                          <button
                            type="button"
                            onClick={() => {
                              setDraft({ ...entry.profile })
                              setTrainingMode(entry.trainingMode)
                              setPreparationRevision(value => value + 1)
                              setShowProfileHistory(false)
                              setStartError(null)
                            }}
                            className="shrink-0 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700"
                          >
                            一键使用
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>

            <CustomerPreparation key={preparationRevision} trainingMode={trainingMode} onProfileChange={setDraft} initialProfile={draft} onStart={startPractice} starting={isStarting} />
            {showVoiceSelector && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-label="AI 声线选择">
              <div className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-white p-6 shadow-2xl">
                <div className="mb-5 flex items-center justify-between gap-4">
                  <div><h3 className="text-xl font-semibold text-gray-900">AI 声线选择</h3><p className="mt-1 text-sm text-gray-500">仅用于当前这场对练；开启新对练会恢复默认男声。</p></div>
                  <button type="button" onClick={() => setShowVoiceSelector(false)} className="rounded-lg px-3 py-2 text-gray-500 hover:bg-gray-100" aria-label="关闭声线选择">关闭</button>
                </div>
                <VoiceSelector selectedVoice={selectedRoleConfig?.voice || 'male-qn-qingse'} onChange={handleVoiceChange} />
              </div>
            </div>}
          </div>
        )}

        {/* Step 3: Ready State */}
        {currentStep === 'ready' && (
          <div className="bg-white rounded-xl shadow-sm p-8 text-center">
            <div className="w-16 h-16 bg-success/10 rounded-full flex items-center justify-center mx-auto mb-4">
              <svg className="w-8 h-8 text-success" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <h2 className="text-xl font-semibold text-gray-900 mb-2">对练已准备就绪</h2>
            <p className="text-gray-500 mb-6">
              对象信息已确认，即将开始针对性对练
            </p>

            <div className="bg-gray-50 rounded-lg p-4 mb-6 text-left">
              <h3 className="font-medium text-gray-700 mb-2">当前配置</h3>
              <div className="space-y-2 text-sm">
                <p><span className="text-gray-500">场景:</span> {moduleTitle}</p>
                <p><span className="text-gray-500">角色:</span> {selectedRoleConfig?.position_level} / {selectedRoleConfig?.personality} / {selectedRoleConfig?.decision_style}</p>
              </div>
            </div>

            <div className="flex justify-center gap-4">
              <button
                onClick={handleReset}
                className="px-6 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50"
              >
                重新开始
              </button>
              <button
                onClick={() => navigate('/practice/chat')}
                className="px-6 py-2 bg-primary text-white rounded-lg hover:bg-primary/90"
              >
                进入对练
              </button>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}

// Step Indicator Component
const StepIndicator = ({ number, label, active, completed }: { number: number; label: string; active: boolean; completed: boolean }) => (
  <div className="flex items-center gap-2">
    <div className={`
      w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium
      ${completed ? 'bg-primary text-white' : active ? 'bg-primary text-white' : 'bg-gray-200 text-gray-500'}
    `}>
      {completed ? (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        </svg>
      ) : number}
    </div>
    <span className={`text-sm ${active ? 'text-primary font-medium' : 'text-gray-500'}`}>{label}</span>
  </div>
)

export default PracticePage
