/**
 * PracticeChatPage - Real-time practice chat page
 *
 * Features:
 * - WebSocket connection for real-time messaging
 * - Phase progress tracking
 * - AI customer persona display
 * - Message history
 * - Phase summary triggers
 *
 * Story: 1.2 语音对话与实时交互
 */
import { useEffect, useState, useCallback, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import axios from 'axios'
import { usePracticeStore } from '../../stores/practiceStore'
import { useWebSocket, StreamMessage, KnowledgeRef } from '../../hooks/useWebSocket'
import { useAudioStream } from '../../hooks/useAudioStream'
import ChatContainer from '../../components/business/practice/ChatContainer'
import PhaseSummaryModal from '../../components/business/practice/PhaseSummaryModal'
import SpinStageHint from '../../components/business/practice/SpinStageHint'
import PracticeMaterialsPanel from '../../components/business/practice/PracticeMaterialsPanel'
import api, { RoleConfig } from '../../api/practice'
import { loadSessionHistory } from '../../utils/sessionHistory'

interface MessageItem {
  id: string
  type: 'user' | 'ai' | 'system'
  content: string
  audioData?: string  // base64 encoded audio for replay
  isSending?: boolean
  timestamp: string
  knowledgeRefs?: KnowledgeRef[]
}

interface PhaseSummaryData {
  phase: string
  phase_label: string
  overall_score: number
  situation_score: number
  problem_score: number
  implication_score: number
  need_payoff_score: number
  good_points: string[]
  improvements: string[]
  suggestions: string[]
}

interface SpinGuidanceData {
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

const INITIAL_SPIN_GUIDANCE: SpinGuidanceData = {
  phase: 'Situation',
  focus: '先了解孩子当前情况和家长最希望改善的目标',
  parent_facts: [],
  unknowns: [
    '孩子的年级、学段和目前学习状态',
    '家长这次最关注的目标或困难',
    '已经尝试过的方法及效果',
  ],
  next_step: '先问孩子目前几年级，以及家长今天最想解决什么问题。',
  reminder: '先听清情况和顾虑，再决定是否介绍课程；价格、效果和政策以知识库资料为准。',
  script: '方便先说说孩子目前几年级吗？您这次最希望优先改善哪方面？',
  references: [],
  not_found: false,
  searched: false,
  isInitial: true,
}

async function blobToBase64(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer())
  let binary = ''
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000))
  }
  return btoa(binary)
}

const PracticeChatPage = () => {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const {
    currentSession,
    selectedScenario,
    selectedRoleConfig,
    updateSessionPhase,
    updatePersona,
    resumeSession
  } = usePracticeStore()

  const [messages_, setMessages_] = useState<MessageItem[]>([])
  const [isSending, setIsSending] = useState(false)
  const [isSummaryModalOpen, setIsSummaryModalOpen] = useState(false)
  const [currentPhaseSummary, setCurrentPhaseSummary] = useState<PhaseSummaryData | null>(null)
  const [isSummaryLoading, setIsSummaryLoading] = useState(false)
  const [spinGuidance, setSpinGuidance] = useState<SpinGuidanceData | null>(null)
  const [spinGuidanceStatus, setSpinGuidanceStatus] = useState<'updating' | 'updated' | 'error' | null>(null)
  const targetSessionId = searchParams.get('sessionId') || currentSession?.id || null
  const [loadedSessionId, setLoadedSessionId] = useState<string | null>(null)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [historyRetry, setHistoryRetry] = useState(0)

  // Track current AI message ID for audio chunk accumulation
  const currentAIMessageIdRef = useRef<string | null>(null)

  // Audio streaming for TTS playback
  const audioStream = useAudioStream()

  const playMessageAudio = useCallback(async (audioData: string, messageId?: string) => {
    if (!audioData.startsWith('/api/v1/')) {
      audioStream.playStoredAudio(audioData, messageId)
      return
    }
    try {
      const { data } = await axios.get<Blob>(audioData, { responseType: 'blob' })
      audioStream.playStoredAudio(await blobToBase64(data), messageId)
    } catch (error) {
      console.error('Failed to load saved practice audio', error)
    }
  }, [audioStream.playStoredAudio])

  // First message comes from WebSocket (ai_message with empty audio_data,
// then ai_message_audio with the audio). No local fallback - backend
// always sends it.

  // 销售员自填的练习档案（从 practiceStore 传过来，banner 展示用）
  const userContext = (currentSession?.user_context || (selectedRoleConfig as any)?.__userContext) as
    | {
        sales_level?: string
        years_experience?: number
        practice_goals?: string[]
        difficulty?: string
        notes?: string
      }
    | undefined
  const practiceGoals = userContext?.practice_goals ?? []

  useEffect(() => {
    if (!targetSessionId) {
      navigate('/practice')
      return
    }
    const controller = new AbortController()
    setLoadedSessionId(null)
    setHistoryError(null)
    setMessages_([])
    setSpinGuidance(null)
    setSpinGuidanceStatus(null)
    currentAIMessageIdRef.current = null
    void loadSessionHistory(targetSessionId, controller.signal).then(({ session, messages }) => {
      if (controller.signal.aborted) return
      resumeSession(session)
      setMessages_(messages)
      setLoadedSessionId(session.id)
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return
      setHistoryError(axios.isAxiosError(error) && typeof error.response?.data?.detail === 'string'
        ? error.response.data.detail : '历史记录加载失败，请重试；不会创建新会话。')
    })
    return () => controller.abort()
  }, [targetSessionId, historyRetry, resumeSession, navigate])

  // Build WebSocket URL - 走 vite 代理（同页同源，自动跟随 vite.config.ts 的 target）
  // 这样切换后端端口只改一处；硬编码后端地址会绕过 Vite proxy
  const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsUrl = loadedSessionId === targetSessionId && currentSession?.status === 'active' && currentSession.id.length > 10
    ? `${wsProtocol}//${window.location.host}/ws/practice/${currentSession.id}`
    : null

  const handleMessage = useCallback((wsMessage: StreamMessage) => {
    if (wsMessage.type === 'spin_guidance_status') {
      const status = wsMessage.data?.status
      if (status === 'updating' || status === 'updated' || status === 'error') setSpinGuidanceStatus(status)
      return
    }
    if (wsMessage.type === 'spin_guidance' && wsMessage.data) {
      setSpinGuidance(wsMessage.data as unknown as SpinGuidanceData)
      setSpinGuidanceStatus('updated')
      return
    }
    // Handle different message types from WebSocket
    if (wsMessage.type === 'user_message') {
      // User's own message - already added locally
      return
    }

    // Backend confirms the user message and includes the ASR transcript
    // (so the local bubble can be updated with the canonical Chinese text).
    if (wsMessage.type === 'user_message_ack') {
      const targetId = wsMessage.id
      const asrText = (wsMessage.data?.asr_text as string)
        || (wsMessage as any).asr_text
        || ''
      console.log('[ACK] msg keys:', Object.keys(wsMessage), 'id:', wsMessage.id, 'data:', wsMessage.data, 'asr_text:', (wsMessage as any).asr_text)
      // Replace the bubble content whenever the backend gives us text.
      // - If ASR succeeds, the bubble gets the real transcript.
      // - If ASR fails, the backend sends a "没听清" notice
      //   so the user knows their message wasn't understood (instead of
      //   staring at "语音消息（4秒）" forever).
      // Don't replace user-typed text — only replace placeholder content.
      // Placeholders: "语音消息（X秒）" / "[语音消息（X秒）]" /
      //               "[系统：没听清...]" / "[系统：语音识别出错...]"
      const isPlaceholder = (content: string) =>
        !content ||
        content.startsWith('[语音消息') ||
        content.startsWith('语音消息（') ||
        content.startsWith('[系统：')
      if (targetId && asrText && asrText !== '[语音消息]') {
        setMessages_(prev => prev.map(m => {
          if (m.id !== targetId) {
            return m
          }
          // Only overwrite if the current content is still a placeholder
          // (don't clobber a transcript the user has since edited).
          if (!isPlaceholder(m.content)) {
            console.log('[ACK] skip msg (not placeholder):', m.content.slice(0, 30))
            return m
          }
          console.log('[ACK] updating bubble', m.id, '→', asrText.slice(0, 30))
          return { ...m, content: asrText }
        }))
      }
      return
    }

    if (wsMessage.type === 'ai_streaming_start') {
      // AI response starting - create new message with empty audioData
      const contentPrefix = wsMessage.content || wsMessage.data?.content_prefix as string || ''
      const newMsgId = wsMessage.id || `msg-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
      currentAIMessageIdRef.current = newMsgId
      const newMessage: MessageItem = {
        id: newMsgId,
        type: 'ai',
        content: contentPrefix,
        audioData: '', // Start with empty audio
        timestamp: wsMessage.timestamp || new Date().toISOString()
      }
      setMessages_(prev => prev.some(m => m.id === newMsgId) ? prev : [...prev, newMessage])
      return
    }

    if (wsMessage.type === 'ai_message' || wsMessage.type === 'ai_streaming_end') {
      // Final AI message with audio from backend
      const content = wsMessage.content || wsMessage.data?.content as string || ''
      const audioData = wsMessage.audio_data || ''
      // Backend can attach a freshly-generated persona on the first ai_message
      const persona = (wsMessage as any).persona
      if (persona && persona.name) {
        updatePersona(persona)
      }
      if (content) {
        const newMsgId = wsMessage.id || (wsMessage.type === 'ai_streaming_end' ? currentAIMessageIdRef.current : null) || `msg-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
        currentAIMessageIdRef.current = newMsgId
        // Pull knowledge_refs from the message (RAG context) so the chat UI
        // can show "参考资料 (N)" footer under the AI bubble.
        const knowledgeRefs = Array.isArray(wsMessage.knowledge_refs) ? wsMessage.knowledge_refs : []
        // Upsert: if a message with this id already exists (e.g. placeholder → LLM text),
        // update it; otherwise append.
        setMessages_(prev => {
          const existingIdx = prev.findIndex(m => m.id === newMsgId)
          if (existingIdx >= 0) {
            const updated = [...prev]
            updated[existingIdx] = {
              ...updated[existingIdx],
              content,
              audioData: audioData || updated[existingIdx].audioData,
              knowledgeRefs: knowledgeRefs.length > 0 ? knowledgeRefs : updated[existingIdx].knowledgeRefs,
              timestamp: wsMessage.timestamp || updated[existingIdx].timestamp
            }
            return updated
          }
          return [...prev, {
            id: newMsgId,
            type: 'ai' as const,
            content,
            audioData,
            knowledgeRefs: knowledgeRefs.length > 0 ? knowledgeRefs : undefined,
            timestamp: wsMessage.timestamp || new Date().toISOString()
          }]
        })

        // Play audio if available (only on first appearance, not on upsert)
        if (audioData && audioData.length > 0) {
          audioStream.autoPlayStoredAudio(audioData, newMsgId)
        }
      }
      return
    }

    // Audio update for an existing message (e.g. first message after TTS finishes)
    if (wsMessage.type === 'ai_message_audio') {
      const targetId = wsMessage.id
      const audioData = wsMessage.audio_data || ''
      if (targetId && audioData) {
        setMessages_(prev => prev.map(m =>
          m.id === targetId ? { ...m, audioData } : m
        ))
        // Play it once
        audioStream.autoPlayStoredAudio(audioData, targetId)
      }
      return
    } else if (wsMessage.type === 'ai_streaming_update') {
      const contentPrefix = wsMessage.content || wsMessage.data?.content_prefix as string || ''
      if (contentPrefix) {
        const targetId = wsMessage.id || currentAIMessageIdRef.current || `msg-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
        currentAIMessageIdRef.current = targetId
        setMessages_(prev => {
          if (prev.some(m => m.id === targetId)) {
            return prev.map(m => m.id === targetId ? { ...m, content: contentPrefix } : m)
          }
          return [...prev, {
            id: targetId,
            type: 'ai' as const,
            content: contentPrefix,
            timestamp: wsMessage.timestamp || new Date().toISOString()
          }]
        })
      }
    }

    // phase_complete 消息不再处理：硬性阶段切换已废弃
    // （A1 改动：让对话按真实节奏走，AI 客户按自己判断回应）

    // Handle backchannel (listening acknowledgment)
    if (wsMessage.type === 'backchannel') {
      console.log('[Backchannel]', wsMessage.content)
    }
  }, [updateSessionPhase, updatePersona])

  const handleConnected = useCallback(() => {
    console.log('WebSocket connected')
  }, [])

  const handleDisconnected = useCallback(() => {
    console.log('WebSocket disconnected')
  }, [])

  const { isConnected, isConnecting, connectionError, reconnect, sendMessage: wsSendMessage, sendStopPlayback, sendVoiceStart, sendVoiceEnd, sendAudioChunk } = useWebSocket({
    url: wsUrl,
    onMessage: handleMessage,
    onAudioChunk: (chunk) => {
      // Play audio immediately when received
      audioStream.playChunk(chunk, currentAIMessageIdRef.current || undefined)
    },
    onConnected: handleConnected,
    onDisconnected: handleDisconnected
  })

  const handleSendMessage = useCallback((content: string, audioData?: string) => {
    // Add user message to local state
    const userMsg: MessageItem = {
      id: `msg-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
      type: 'user',
      content,
      audioData: audioData || undefined,
      isSending: true,
      timestamp: new Date().toISOString()
    }
    setMessages_(prev => [...prev, userMsg])

    setIsSending(true)

    // Send via WebSocket (include id so the ASR ack can be matched back)
    wsSendMessage(content, audioData, userMsg.id, 'audio/webm')

    // Update message status to show sending
    setMessages_(prev => prev.map(m =>
      m.id === userMsg.id ? { ...m, isSending: false } : m
    ))
    setIsSending(false)
  }, [wsSendMessage])

  // OR-1: Handle stop playback (interrupt AI speech and notify server)
  const handleStopPlayback = useCallback(() => {
    audioStream.stop()
    sendStopPlayback()  // Notify server to stop TTS
  }, [audioStream, sendStopPlayback])

  // Get role configuration labels
  const getRoleLabel = (config: RoleConfig | null, key: keyof RoleConfig) => {
    if (!config?.[key]) return ''
    const labels: Record<string, Record<string, string>> = {
      position_level: { junior: '初级客户经理', middle: '中级采购经理', senior: '高级总监' },
      personality: { rational: '理性型', emotional: '感性型', hesitant: '犹豫型', decisive: '果断型' },
      decision_style: { price_oriented: '价格导向', value_oriented: '价值导向', relationship_oriented: '关系导向', risk_averse: '风险规避' }
    }
    return labels[key]?.[config[key] as string] || config[key] as string
  }

  // Handle phase summary request
  const handleGetPhaseSummary = useCallback(async () => {
    if (!currentSession?.id || !currentSession?.current_phase) return

    setIsSummaryModalOpen(true)
    setIsSummaryLoading(true)
    setCurrentPhaseSummary(null)

    try {
      // Call the actual API
      const response = await api.getPhaseSummary(currentSession.id, currentSession.current_phase)
      setCurrentPhaseSummary(response)
      const summaryIssue = response.suggestions?.[0] || response.improvements?.[0]
      if (summaryIssue) {
        setSpinGuidance(previous => previous
          ? { ...previous, reminder: `本阶段提醒：${summaryIssue.slice(0, 96)}` }
          : previous)
      }
    } catch (error) {
      console.error('Failed to get phase summary:', error)
      // Fallback to minimal demo data on error
      setCurrentPhaseSummary({
        phase: currentSession.current_phase,
        phase_label: ['开场破冰', '需求挖掘', '方案呈现', '促成成交', '复盘总结'][
          ['opening', 'discovery', 'needs', 'proposal', 'closing'].indexOf(currentSession.current_phase)
        ] || currentSession.current_phase,
        overall_score: 0,
        situation_score: 0,
        problem_score: 0,
        implication_score: 0,
        need_payoff_score: 0,
        good_points: ['数据加载失败，请重试'],
        improvements: ['后端API调用失败'],
        suggestions: ['请检查后端服务是否正常运行']
      })
    } finally {
      setIsSummaryLoading(false)
    }
  }, [currentSession])

  if (historyError) return (
    <div role="alert" className="p-8 text-center space-y-4">
      <p>{historyError}</p>
      <button onClick={() => setHistoryRetry(value => value + 1)} className="text-primary underline">重新加载历史记录</button>
      <button onClick={() => navigate('/history')} className="ml-4 text-primary underline">返回历史记录</button>
    </div>
  )
  if (loadedSessionId !== targetSessionId || !targetSessionId) return (
    <div role="status" className="p-8 text-center text-gray-500">正在恢复上次对话和设置…</div>
  )

  return (
    <div className="flex flex-col h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-sm px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate('/practice')}
            className="p-2 hover:bg-gray-100 rounded-lg"
          >
            <svg className="w-5 h-5 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <div>
            <h1 className="font-semibold text-gray-900">{selectedScenario?.name || '对练中'}</h1>
            <p className="text-xs text-gray-500">
              {currentSession?.status === 'completed' ? '历史对话 · 已结束' : isConnected ? (
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 bg-success rounded-full" />
                  已连接
                </span>
              ) : (
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 bg-yellow-500 rounded-full animate-pulse" />
                  {isConnecting ? '连接中…' : '连接未建立'}
                </span>
              )}
            </p>
          </div>
        </div>

        {/* AI Customer Persona - shows concrete character (persona) when available */}
        {currentSession?.persona ? (
          <div className="flex items-center gap-3 px-4 py-2 bg-gray-50 rounded-lg max-w-md">
            <div className="w-10 h-10 bg-secondary/10 rounded-full flex items-center justify-center flex-shrink-0">
              <svg className="w-5 h-5 text-secondary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
              </svg>
            </div>
            <div className="text-sm min-w-0 flex-1">
              <p className="font-medium text-gray-900 truncate">
                {currentSession.persona.name} · {currentSession.persona.title}
              </p>
              <p className="text-gray-500 truncate">
                {currentSession.persona.company}
                {currentSession.persona.industry && ` · ${currentSession.persona.industry}`}
              </p>
            </div>
          </div>
        ) : selectedRoleConfig ? (
          <div className="flex items-center gap-3 px-4 py-2 bg-gray-50 rounded-lg">
            <div className="w-10 h-10 bg-secondary/10 rounded-full flex items-center justify-center">
              <svg className="w-5 h-5 text-secondary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
              </svg>
            </div>
            <div className="text-sm">
              <p className="font-medium text-gray-900">
                正在生成客户档案...
              </p>
              <p className="text-gray-500">
                {getRoleLabel(selectedRoleConfig, 'position_level')} · {getRoleLabel(selectedRoleConfig, 'personality')}
              </p>
            </div>
          </div>
        ) : null}
      </header>

      {/* 自由对话指示条（替代旧的硬性 5 阶段 SPIN 进度条） */}
      <div className="bg-white border-b border-gray-200 px-4 py-2">
        <div className="flex items-center gap-2 text-sm text-gray-600">
          <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-green-50 text-green-700 rounded">
            <span className="w-1.5 h-1.5 bg-green-500 rounded-full animate-pulse"></span>
            {currentSession?.training_mode === 'rejection' ? '拒绝挽回' : '完整销售对练'}
          </span>
          {currentSession?.persona?.name && (
            <span className="text-gray-500">
              · 正在和【{currentSession.persona.name}】聊天
            </span>
          )}
          {/* 销售员自填的练习档案徽章 */}
          {userContext && (
            <span className="text-gray-500 truncate">
              {practiceGoals.length > 0 &&
                `· 重点练: ${practiceGoals.join('/')}`}
              {userContext.difficulty && ` · 难度: ${userContext.difficulty}`}
            </span>
          )}
        </div>
      </div>

      {/* Chat Area with SPIN Stage Hint */}
      <div className="flex-1 overflow-hidden flex">
        <div className="flex-1">
          <ChatContainer
            messages={messages_}
            customerLabel={
              currentSession?.persona
                ? `${currentSession.persona.name}${currentSession.persona.title ? '·' + currentSession.persona.title.split('经理')[0].split('总监')[0] : ''}`
                : 'AI客户'
            }
            onSendMessage={handleSendMessage}
            onVoiceStart={sendVoiceStart}
            onVoiceEnd={sendVoiceEnd}
            onAudioChunk={sendAudioChunk}
            onStopPlayback={handleStopPlayback}
            onPlayAudio={playMessageAudio}
            isDisabled={currentSession?.status === 'completed'}
            isSending={isSending}
            isConnected={isConnected}
            connectionError={connectionError}
            onReconnect={reconnect}
            isPlayingAudio={audioStream.isPlaying}
            isPausedAudio={audioStream.isPaused}
            activeAudioMessageId={audioStream.activeMessageId}
            onPauseAudio={audioStream.pause}
            onResumeAudio={audioStream.resume}
          />
        </div>
        {/* OR-4: Real-time SPIN Stage Hint Sidebar */}
        <div className="w-80 border-l border-gray-200 bg-gray-50 overflow-y-auto p-3">
          <div className="mb-3 flex items-center justify-between gap-2">
            <p className="text-xs font-medium text-gray-500">实时SPIN指导</p>
            <PracticeMaterialsPanel
              sessionId={currentSession?.id}
              profile={currentSession?.customer_context?.preparation}
              references={spinGuidance?.references || []}
              searched={spinGuidance?.searched}
              notFound={spinGuidance?.not_found}
              searchError={spinGuidance?.search_error}
              searchQuery={spinGuidance?.last_search_query}
              updatedAt={spinGuidance?.updated_at}
            />
          </div>
          <SpinStageHint
            key={currentSession?.id}
            guidance={spinGuidance || INITIAL_SPIN_GUIDANCE}
            updateStatus={spinGuidanceStatus}
          />
        </div>
      </div>

      {/* Summary Button */}
      <div className="bg-white border-t border-gray-200 px-4 py-3 flex justify-between items-center">
        <div className="text-sm text-gray-500">
          当前阶段: <span className="font-medium text-primary">
            {currentSession?.current_phase === 'opening' && '开场破冰'}
            {currentSession?.current_phase === 'discovery' && '需求挖掘'}
            {currentSession?.current_phase === 'needs' && '方案呈现'}
            {currentSession?.current_phase === 'proposal' && '促成成交'}
            {currentSession?.current_phase === 'closing' && '复盘总结'}
          </span>
        </div>
        <button
          onClick={handleGetPhaseSummary}
          disabled={currentSession?.status === 'completed'}
          className="px-4 py-2 bg-secondary text-white rounded-lg hover:bg-secondary/90 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium transition-all"
        >
          生成阶段总结
        </button>
      </div>

      {/* Phase Summary Modal */}
      <PhaseSummaryModal
        isOpen={isSummaryModalOpen}
        onClose={() => setIsSummaryModalOpen(false)}
        summary={currentPhaseSummary}
        isLoading={isSummaryLoading}
        sessionId={currentSession?.id}
      />
    </div>
  )
}

export default PracticeChatPage
