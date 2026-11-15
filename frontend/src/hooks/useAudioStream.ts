/**
 * useAudioStream - Streaming audio playback hook
 * Handles chunked audio playback with interruption support.
 * P4: 用 Web Audio API 实时解码 + 排队播放（替代累积 blob 后再播），
 * 第一个 mp3 chunk 到达后 ~0.3s 即可开始播放。
 */
import { useState, useRef, useCallback } from 'react'

// Ensure AudioContext is available
declare const AudioContext: typeof undefined | ((options?: any) => any)

interface UseAudioStreamReturn {
  activeMessageId: string | null
  isPaused: boolean
  isPlaying: boolean
  isBuffering: boolean
  currentPosition: number
  duration: number
  playChunk: (chunk: Uint8Array, messageId?: string) => void
  playBase64Chunk: (base64: string) => void
  autoPlayStoredAudio: (base64Audio: string, messageId: string) => void
  playStoredAudio: (base64Audio: string, messageId?: string) => void
  stop: () => void
  pause: () => void
  resume: () => void
  currentAudioUrl: string | null
}

export function useAudioStream(): UseAudioStreamReturn {
  const autoPlayedRef = useRef(new Set<string>())
  const streamMessageRef = useRef<string | null>(null)
  const [activeMessageId, setActiveMessageId] = useState<string | null>(null)
  const [isPaused, setIsPaused] = useState(false)
  const pausedRef = useRef(false)
  const [isPlaying, setIsPlaying] = useState(false)
  const [isBuffering, setIsBuffering] = useState(false)
  const [currentPosition, setCurrentPosition] = useState(0)
  const [duration, setDuration] = useState(0)

  const audioElementRef = useRef<HTMLAudioElement | null>(null)
  const chunkQueueRef = useRef<Uint8Array[]>([])
  const isPlayingRef = useRef(false)
  const isInterruptedRef = useRef(false)
  const currentUrlRef = useRef<string | null>(null)

  // P4: Web Audio API 实时流式播放
  const audioCtxRef = useRef<AudioContext | null>(null)
  // mp3 累积器（mp3 头在第一个 chunk，frame 在后续 chunks）
  const mp3AccumRef = useRef<Uint8Array[]>([])
  // 解码后待播的 AudioBuffer 队列
  const pendingBuffersRef = useRef<AudioBuffer[]>([])
  // 下一次播放的开始时间（用 AudioContext.currentTime + offset）
  const nextStartTimeRef = useRef<number>(0)
  // 排队播放用的 Interval ID
  const drainIntervalRef = useRef<number | null>(null)

  const ensureAudioContext = useCallback((): AudioContext | null => {
    if (typeof window === 'undefined') return null
    const Ctx = (window as any).AudioContext || (window as any).webkitAudioContext
    if (!Ctx) return null
    const ctx = audioCtxRef.current ?? new Ctx()
    audioCtxRef.current = ctx
    // 用户交互后 audioCtx 可能被挂起，需要 resume
    if (ctx.state === 'suspended' && !pausedRef.current) {
      ctx.resume().catch(() => {})
    }
    return ctx
  }, [])

  const drainQueue = useCallback(() => {
    const ctx = audioCtxRef.current
    if (!ctx || pausedRef.current) return
    while (pendingBuffersRef.current.length > 0) {
      const buf = pendingBuffersRef.current.shift()!
      const startAt = Math.max(ctx.currentTime, nextStartTimeRef.current)
      const src = ctx.createBufferSource()
      src.buffer = buf
      src.connect(ctx.destination)
      src.start(startAt)
      nextStartTimeRef.current = startAt + buf.duration
      // 最后一个 source 结束时设 isPlaying=false
      src.onended = () => {
        if (audioCtxRef.current !== ctx) return
        if (!pausedRef.current && pendingBuffersRef.current.length === 0 && ctx.currentTime >= nextStartTimeRef.current) {
          // 给 50ms 缓冲看还有没有新 buffer 进来
          setTimeout(() => {
            if (audioCtxRef.current !== ctx) return
            if (!pausedRef.current && pendingBuffersRef.current.length === 0 && ctx.currentTime >= nextStartTimeRef.current) {
              setIsPlaying(false)
              isPlayingRef.current = false
            }
          }, 100)
        }
      }
    }
  }, [])

  const processQueue = useCallback(() => {
    console.log('[AudioStream] processQueue called, queue length:', chunkQueueRef.current.length)
    if (pausedRef.current || chunkQueueRef.current.length === 0) {
      console.log('[AudioStream] Queue empty, returning')
      return
    }

    isInterruptedRef.current = false
    setIsBuffering(true)

    // Combine all queued chunks
    const totalLength = chunkQueueRef.current.reduce((sum, chunk) => sum + chunk.length, 0)
    console.log('[AudioStream] Combining', chunkQueueRef.current.length, 'chunks, total size:', totalLength)
    const combinedBuffer = new Uint8Array(totalLength)
    let offset = 0
    for (const chunk of chunkQueueRef.current) {
      combinedBuffer.set(chunk, offset)
      offset += chunk.length
    }
    chunkQueueRef.current = []

    // Clean up previous audio
    if (audioElementRef.current) {
      const previous = audioElementRef.current
      audioElementRef.current = null
      previous.pause()
      previous.src = ''
    }
    if (currentUrlRef.current) {
      URL.revokeObjectURL(currentUrlRef.current)
      currentUrlRef.current = null
    }

    // MiniMax TTS returns standard MP3 format (OpenAI-compatible API)
    // Use HTML5 Audio with blob URL for reliable MP3 playback
    const blob = new Blob([combinedBuffer], { type: 'audio/mpeg' })
    const url = URL.createObjectURL(blob)
    currentUrlRef.current = url
    console.log('[AudioStream] Created MP3 blob URL')

    const audio = new Audio(url)
    audioElementRef.current = audio

    audio.onloadedmetadata = () => {
        if (audioElementRef.current !== audio) return
      console.log('[AudioStream] Metadata loaded, duration:', audio.duration)
      setDuration(audio.duration)
      setIsBuffering(false)
    }

    audio.onplay = () => {
        if (audioElementRef.current !== audio) return
      console.log('[AudioStream] Playing MP3!')
      setIsPlaying(true)
      isPlayingRef.current = true
      setIsBuffering(false)
    }

    audio.onended = () => {
        if (audioElementRef.current !== audio) return
      console.log('[AudioStream] Ended')
      if (!isInterruptedRef.current) {
        setIsPlaying(false)
        setCurrentPosition(0)
        isPlayingRef.current = false
      }
    }

    audio.onerror = () => {
        if (audioElementRef.current !== audio) return
      console.error('[AudioStream] MP3 Audio error:', audio.error)
      setIsPlaying(false)
      setIsBuffering(false)
      isPlayingRef.current = false
    }

    audio.ontimeupdate = () => {
        if (audioElementRef.current !== audio) return
      setCurrentPosition(audio.currentTime)
    }

    audio.preload = 'auto'
    console.log('[AudioStream] Calling audio.play()')
    audio.play().catch(err => {
        if (audioElementRef.current !== audio) return
      console.error('[AudioStream] Play error:', err)
      setIsPlaying(false)
      setIsBuffering(false)
      isPlayingRef.current = false
    })
  }, [])

  const playChunk = useCallback((chunk: Uint8Array, messageId?: string) => {
    if (messageId && streamMessageRef.current !== messageId) {
      streamMessageRef.current = messageId
      isInterruptedRef.current = false
      pausedRef.current = false
      setIsPaused(false)
    }
    if (messageId) setActiveMessageId(messageId)
    const ctx = ensureAudioContext()
    if (!ctx) {
      // Web Audio 不可用：降级用旧逻辑（累积到齐后用 HTML5 Audio 播）
      chunkQueueRef.current.push(chunk)
      if (!isPlayingRef.current) processQueue()
      return
    }
    // P4: 把 chunk 累积到 mp3 缓冲，等解码出 AudioBuffer 后立即入队播放
    mp3AccumRef.current.push(chunk)
    // 合并所有累积的 mp3 字节，尝试 decodeAudioData
    const totalLen = mp3AccumRef.current.reduce((s, c) => s + c.length, 0)
    const combined = new Uint8Array(totalLen)
    let off = 0
    for (const c of mp3AccumRef.current) { combined.set(c, off); off += c.length }

    // 累积到 8KB 以上再尝试解码（mp3 frame 通常 1-2KB，8KB 大概率有完整 frame）
    if (combined.length < 8192 && pendingBuffersRef.current.length === 0) {
      return
    }
    // 把 combined copy 出来（不要消耗 mp3AccumRef，否则下个 chunk 重复数据）
    const toDecode = combined.slice()

    // 异步 decode
    ctx.decodeAudioData(toDecode.buffer.slice(toDecode.byteOffset, toDecode.byteOffset + toDecode.byteLength))
      .then((audioBuf) => {
        if (isInterruptedRef.current || audioCtxRef.current !== ctx) return
        if (messageId) autoPlayedRef.current.add(messageId)
        pendingBuffersRef.current.push(audioBuf)
        // 重置 mp3 累积器（已成功解码）
        mp3AccumRef.current = []
        if (!isPlayingRef.current && !pausedRef.current) {
          isPlayingRef.current = true
          setIsPlaying(true)
          if (nextStartTimeRef.current < ctx.currentTime) {
            nextStartTimeRef.current = ctx.currentTime + 0.05  // 50ms 缓冲
          }
          drainQueue()
        }
      })
      .catch((err) => {
        // mp3 头不完整或解码失败 — 不重置 mp3AccumRef，等下一个 chunk
        console.warn('[AudioStream] decodeAudioData failed (will retry with more chunks):', err.message)
      })
  }, [ensureAudioContext, drainQueue, processQueue])

  const playBase64Chunk = useCallback((base64: string) => {
    const binaryString = atob(base64)
    const bytes = new Uint8Array(binaryString.length)
    for (let i = 0; i < binaryString.length; i++) {
      bytes[i] = binaryString.charCodeAt(i)
    }
    playChunk(bytes)
  }, [playChunk])

  // Play stored/replayed audio from base64
  const playStoredAudio = useCallback((base64Audio: string, messageId?: string) => {
    if (messageId) autoPlayedRef.current.add(messageId)
    setActiveMessageId(messageId || null)
    console.log('[AudioStream] playStoredAudio called, length:', base64Audio.length)

    pausedRef.current = false
    setIsPaused(false)
    void audioCtxRef.current?.close().catch(() => {})
    audioCtxRef.current = null
    pendingBuffersRef.current = []
    mp3AccumRef.current = []
    nextStartTimeRef.current = 0
    // Stop current playback
    isInterruptedRef.current = true
    if (audioElementRef.current) {
      const previous = audioElementRef.current
      audioElementRef.current = null
      previous.pause()
      previous.src = ''
    }

    try {
      // Decode base64
      const binaryString = atob(base64Audio)
      const bytes = new Uint8Array(binaryString.length)
      for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i)
      }
      console.log('[AudioStream] Decoded bytes:', bytes.length)

      // Sniff mime from magic bytes so user-recorded webm/opus and AI mp3 both work
      let mime = 'audio/mpeg'
      if (bytes.length >= 4) {
        // "ID3" (mp3 with ID3 tag) or 0xFF 0xFB/0xFA/0xF3/0xF2 (mp3 frame sync) -> mp3
        if (bytes[0] === 0x49 && bytes[1] === 0x44 && bytes[2] === 0x33) {
          mime = 'audio/mpeg'
        } else if (bytes[0] === 0xFF && (bytes[1] & 0xE0) === 0xE0) {
          mime = 'audio/mpeg'
        } else if (bytes[0] === 0x1A && bytes[1] === 0x45 && bytes[2] === 0xDF) {
          // EBML header (webm/matroska)
          mime = 'audio/webm'
        } else if (bytes[0] === 0x4F && bytes[1] === 0x67 && bytes[2] === 0x67 && bytes[3] === 0x53) {
          // OGG container
          mime = 'audio/ogg'
        } else if (bytes[0] === 0x52 && bytes[1] === 0x49 && bytes[2] === 0x46 && bytes[3] === 0x46) {
          // RIFF (wav)
          mime = 'audio/wav'
        } else if (bytes[0] === 0x66 && bytes[1] === 0x4C && bytes[2] === 0x61 && bytes[3] === 0x43) {
          // FLAC
          mime = 'audio/flac'
        } else if (bytes[0] === 0xFF && bytes[1] === 0xF1) {
          // AAC ADTS
          mime = 'audio/aac'
        }
      }
      console.log('[AudioStream] Detected mime:', mime)

      // Clean up previous URL
      if (currentUrlRef.current) {
        URL.revokeObjectURL(currentUrlRef.current)
        currentUrlRef.current = null
      }

      // Create blob and play
      const blob = new Blob([bytes], { type: mime })
      const url = URL.createObjectURL(blob)
      currentUrlRef.current = url

      const audio = new Audio(url)
      audioElementRef.current = audio

      audio.onloadedmetadata = () => {
        if (audioElementRef.current !== audio) return
        console.log('[AudioStream] Replay metadata loaded, duration:', audio.duration)
        setDuration(audio.duration)
      }

      audio.onplay = () => {
        if (audioElementRef.current !== audio) return
        console.log('[AudioStream] Replay playing!')
        setIsPlaying(true)
        isPlayingRef.current = true
        setIsBuffering(false)
      }

      audio.onended = () => {
        if (audioElementRef.current !== audio) return
        console.log('[AudioStream] Replay ended')
        setIsPlaying(false)
        setCurrentPosition(0)
        isPlayingRef.current = false
      }

      audio.onerror = () => {
        if (audioElementRef.current !== audio) return
        console.error('[AudioStream] Replay error:', audio.error, 'mime:', mime)
        setIsPlaying(false)
        setIsBuffering(false)
        isPlayingRef.current = false
      }

      audio.ontimeupdate = () => {
        if (audioElementRef.current !== audio) return
        setCurrentPosition(audio.currentTime)
      }

      audio.preload = 'auto'
      audio.play().catch(err => {
        if (audioElementRef.current !== audio) return
        console.error('[AudioStream] Replay play error:', err)
        setIsPlaying(false)
        setIsBuffering(false)
        isPlayingRef.current = false
      })
    } catch (e) {
      console.error('[AudioStream] Failed to decode base64:', e)
    }
  }, [])

  // A final/duplicate server update must not restart audio the user paused.
  const autoPlayStoredAudio = useCallback((audio: string, messageId: string) => {
    if (!audio || autoPlayedRef.current.has(messageId)) return
    playStoredAudio(audio, messageId)
  }, [playStoredAudio])

  const stop = useCallback(() => {
    console.log('[AudioStream] stop called')
    pausedRef.current = false
    setIsPaused(false)
    void audioCtxRef.current?.close().catch(() => {})
    audioCtxRef.current = null
    isInterruptedRef.current = true

    if (audioElementRef.current) {
      audioElementRef.current.pause()
      audioElementRef.current.currentTime = 0
    }

    isPlayingRef.current = false
    chunkQueueRef.current = []
    // P4: 清理 Web Audio state
    mp3AccumRef.current = []
    pendingBuffersRef.current = []
    nextStartTimeRef.current = 0
    if (drainIntervalRef.current !== null) {
      clearInterval(drainIntervalRef.current)
      drainIntervalRef.current = null
    }

    setIsPlaying(false)
    setCurrentPosition(0)
    setIsBuffering(false)
  }, [])

  const pause = useCallback(() => {
    if (!isPlayingRef.current) return
    pausedRef.current = true
    setIsPaused(true)
    audioElementRef.current?.pause()
    void audioCtxRef.current?.suspend().catch(() => {})
    isPlayingRef.current = false
    setIsPlaying(false)
  }, [])

  const resume = useCallback(() => {
    if (!pausedRef.current) return
    pausedRef.current = false
    setIsPaused(false)
    const ctx = audioCtxRef.current
    if (ctx) {
      void ctx.resume().then(() => {
        if (pausedRef.current || audioCtxRef.current !== ctx) return
        isPlayingRef.current = true
        setIsPlaying(true)
        drainQueue()
      }).catch(() => { pausedRef.current = true; setIsPaused(true) })
    } else if (audioElementRef.current) {
      void audioElementRef.current.play().catch(() => { pausedRef.current = true; setIsPaused(true) })
    }
  }, [drainQueue])

  return {
    activeMessageId,
    isPaused,
    isPlaying,
    isBuffering,
    currentPosition,
    duration,
    playChunk,
    playBase64Chunk,
    playStoredAudio,
    autoPlayStoredAudio,
    stop,
    pause,
    resume,
    currentAudioUrl: currentUrlRef.current
  }
}
