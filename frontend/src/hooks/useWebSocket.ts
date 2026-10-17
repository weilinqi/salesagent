/**
 * useWebSocket Hook - Enhanced for streaming voice conversation
 * Supports binary audio chunks, state sync, and backchannel
 */
import { useEffect, useRef, useState, useCallback } from 'react'
import { createWebSocketConnection } from './webSocketConnection'
import type { CustomerPersona } from '../stores/practiceStore'

export type ConversationState = 'idle' | 'user_speaking' | 'ai_speaking' | 'processing'

export interface KnowledgeRef {
  category?: string
  source?: string
  chapter?: string
  section?: string
  excerpt?: string
  relevance?: number
}

export interface StreamMessage {
  type: 'user_message' | 'user_message_ack' | 'ai_message' | 'ai_message_audio' | 'ai_streaming_start' | 'ai_streaming_update' |
        'ai_streaming_end' | 'audio_chunk' | 'backchannel' | 'status_update' |
        'stop_playback' | 'playback_stopped' | 'summary_trigger' | 'phase_complete' | 'system'
  id?: string
  content?: string
  audio_data?: string
  asr_text?: string
  persona?: CustomerPersona
  knowledge_refs?: KnowledgeRef[]
  state?: ConversationState
  timestamp: string
  data?: Record<string, unknown>
}

interface UseWebSocketOptions {
  url: string | null
  onMessage?: (message: StreamMessage) => void
  onAudioChunk?: (chunk: Uint8Array) => void
  onStateChange?: (state: ConversationState) => void
  onConnected?: () => void
  onDisconnected?: () => void
  onError?: (error: Event) => void
}

interface UseWebSocketReturn {
  isConnected: boolean
  isConnecting: boolean
  sendMessage: (message: string, audioData?: string, id?: string, audioMime?: string) => void
  sendAudioChunk: (chunk: Uint8Array) => void
  sendStopPlayback: () => void
  sendVoiceStart: () => void
  sendVoiceEnd: () => void
  disconnect: () => void
  lastMessage: StreamMessage | null
  lastAudioChunk: Uint8Array | null
  state: ConversationState
}

export const useWebSocket = ({
  url,
  onMessage,
  onAudioChunk,
  onStateChange,
  onConnected,
  onDisconnected,
  onError
}: UseWebSocketOptions): UseWebSocketReturn => {
  const [isConnected, setIsConnected] = useState(false)
  const [isConnecting, setIsConnecting] = useState(false)
  const [lastMessage, setLastMessage] = useState<StreamMessage | null>(null)
  const [lastAudioChunk, setLastAudioChunk] = useState<Uint8Array | null>(null)
  const [state, setState] = useState<ConversationState>('idle')

  const connectionRef = useRef<ReturnType<typeof createWebSocketConnection> | null>(null)
  const callbacksRef = useRef({ onMessage, onAudioChunk, onStateChange, onConnected, onDisconnected, onError })
  callbacksRef.current = { onMessage, onAudioChunk, onStateChange, onConnected, onDisconnected, onError }

  useEffect(() => {
    let active = true
    setIsConnected(false)
    setIsConnecting(false)
    setState('idle')
    setLastMessage(null)
    setLastAudioChunk(null)
    if (!url) return
    const connection = createWebSocketConnection(url, {
      onConnecting: () => { if (active) setIsConnecting(true) },
      onConnected: () => {
        if (!active) return
        setIsConnected(true)
        setIsConnecting(false)
        callbacksRef.current.onConnected?.()
      },
      onDisconnected: () => {
        if (!active) return
        setIsConnected(false)
        setIsConnecting(false)
        callbacksRef.current.onDisconnected?.()
      },
      onError: error => { if (active) callbacksRef.current.onError?.(error) },
      onMessage: event => {
        if (!active) return
        if (event.data instanceof ArrayBuffer) {
          const chunk = new Uint8Array(event.data)
          setLastAudioChunk(chunk)
          callbacksRef.current.onAudioChunk?.(chunk)
          return
        }
        try {
          const message: StreamMessage = JSON.parse(event.data)
          setLastMessage(message)
          if (message.type === 'status_update' && message.state) {
            setState(message.state)
            callbacksRef.current.onStateChange?.(message.state)
          }
          callbacksRef.current.onMessage?.(message)
        } catch { /* Ignore malformed frames without breaking the connection. */ }
      },
    })
    connectionRef.current = connection
    return () => {
      active = false
      connection.disconnect()
      if (connectionRef.current === connection) connectionRef.current = null
    }
  }, [url])

  const disconnect = useCallback(() => { connectionRef.current?.disconnect() }, [])
  const sendMessage = useCallback((message: string, audioData?: string, id?: string, audioMime?: string) => {
    connectionRef.current?.send(JSON.stringify({
      type: 'user_message', id, content: message, audio_data: audioData,
      audio_mime: audioMime, timestamp: new Date().toISOString(),
    }))
  }, [])
  const sendAudioChunk = useCallback((chunk: Uint8Array) => { connectionRef.current?.send(chunk) }, [])
  const sendStopPlayback = useCallback(() => { connectionRef.current?.send(JSON.stringify({ type: 'stop_playback' })) }, [])
  const sendVoiceStart = useCallback(() => { connectionRef.current?.send(JSON.stringify({ type: 'voice_start' })) }, [])
  const sendVoiceEnd = useCallback(() => { connectionRef.current?.send(JSON.stringify({ type: 'voice_end' })) }, [])
  return {
    isConnected,
    isConnecting,
    sendMessage,
    sendAudioChunk,
    sendStopPlayback,
    sendVoiceStart,
    sendVoiceEnd,
    disconnect,
    lastMessage,
    lastAudioChunk,
    state
  }
}

export default useWebSocket

