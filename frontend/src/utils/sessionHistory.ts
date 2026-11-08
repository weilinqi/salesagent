/**
 * Transcript helpers shared by the history list, the review page and the
 * chat page. Kept free of React so the rules can be unit tested offline.
 */
import type { SessionMessage } from '../api/practice'

export interface TranscriptMessage {
  id: string
  type: 'user' | 'ai' | 'system'
  content: string
  timestamp: string
}

const ROLE_TYPES: Record<string, TranscriptMessage['type']> = {
  user: 'user',
  human: 'user',
  sales: 'user',
  salesperson: 'user',
  ai: 'ai',
  assistant: 'ai',
  customer: 'ai',
  bot: 'ai',
}

/** Map a stored role onto the bubble type the chat UI renders. */
export function toTranscriptType(role?: string | null): TranscriptMessage['type'] {
  return ROLE_TYPES[(role || '').trim().toLowerCase()] || 'system'
}

/**
 * Turn persisted messages into renderable bubbles. Empty turns are dropped
 * so an interrupted save never leaves a blank bubble behind.
 */
export function toTranscriptMessages(
  messages?: SessionMessage[] | null
): TranscriptMessage[] {
  if (!Array.isArray(messages)) return []
  return messages
    .filter(message => message && typeof message.content === 'string')
    .map(message => ({
      id: message.id,
      type: toTranscriptType(message.role),
      content: message.content.trim(),
      timestamp: message.created_at || '',
    }))
    .filter(message => message.content.length > 0)
}

/** Only unfinished sessions can be continued from the history page. */
export function canResumeSession(status?: string | null): boolean {
  const value = (status || '').trim().toLowerCase()
  return value === 'active' || value === 'preparing'
}

/**
 * Format a timestamp for a query parameter.
 *
 * The backend stores naive UTC datetimes, so the value must not carry a
 * timezone offset - otherwise the comparison happens eight hours off.
 */
export function toUtcDateParam(value: Date): string {
  return value.toISOString().replace(/\.\d{3}Z$/, '')
}

/** The start of the given date range, or null when everything is shown. */
export function dateRangeStart(range: string, now: Date = new Date()): Date | null {
  const days = range === '7days' ? 7 : range === '30days' ? 30 : range === '90days' ? 90 : null
  if (days === null) return null
  return new Date(now.getTime() - days * 86400_000)
}

/** Human readable timestamp for a transcript entry. */
export function formatTranscriptTime(value?: string | null): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
