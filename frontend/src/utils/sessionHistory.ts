import api from '../api/practice'

/** Load authoritative history before opening a live socket for this session. */
export async function loadSessionHistory(sessionId: string, signal: AbortSignal) {
  const [session, rows] = await Promise.all([
    api.getSession(sessionId, signal), api.getSessionMessages(sessionId, signal),
  ])
  if (session.id !== sessionId) throw new Error('会话记录不匹配，请重新打开历史记录')
  return {
    session,
    messages: rows.map(row => ({
      id: row.id,
      type: (row.role === 'ai' || row.role === 'assistant' ? 'ai' : row.role) as 'user' | 'ai' | 'system',
      content: row.content,
      timestamp: row.created_at,
    })),
  }
}
