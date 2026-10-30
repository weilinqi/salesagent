import axios, { InternalAxiosRequestConfig } from 'axios'
import type { TokenResponse, User } from './auth'

const STORAGE_KEY = 'sales_agent_auth'
export interface StoredSession { user: User; token: string; refreshToken?: string; sessionId?: string }
let version = 0
const listeners = new Set<() => void>()
let renewal: { version: number; promise: Promise<string> } | null = null

export class SessionChangedError extends Error {
  constructor() { super('登录会话已更换'); this.name = 'SessionChangedError' }
}
const sessionIdentity = (session: StoredSession | null) => session?.sessionId || session?.user.id || null
let observedIdentity: string | null = sessionIdentity(readSession())
function synchronizeSession() {
  const identity = sessionIdentity(readSession())
  if (identity !== observedIdentity) {
    observedIdentity = identity
    version++
    notify()
  }
}
export const getSessionVersion = () => { synchronizeSession(); return version }
export const isCurrentSession = (expected: number) => { synchronizeSession(); return expected === version }
export function readSession(): StoredSession | null {
  try {
    const session = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null')
    if (session?.user && typeof session.token === 'string' && session.token) {
      return { ...session, refreshToken: session.refreshToken || session.refresh_token }
    }
  } catch { /* Corrupt storage is treated as a signed-out session. */ }
  return null
}
export const getAccessToken = () => readSession()?.token || null
export function subscribeSession(listener: () => void) {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}
function notify() { listeners.forEach(listener => listener()) }
export function clearSession(expected = version) {
  if (!isCurrentSession(expected)) return
  version++
  localStorage.removeItem(STORAGE_KEY)
  observedIdentity = null
  notify()
}
export function saveSession(response: TokenResponse, expected = version) {
  if (!isCurrentSession(expected)) throw new SessionChangedError()
  const sessionId = readSession()?.sessionId ||
    (typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`)
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ user: response.user, token: response.access_token, refreshToken: response.refresh_token, sessionId }))
  observedIdentity = sessionId
  notify()
}
export function saveSessionUser(user: User, expected: number) {
  const session = readSession()
  if (!session || !isCurrentSession(expected)) return
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...session, user }))
  notify()
}
export function isInvalidSessionError(error: unknown) {
  return axios.isAxiosError(error) && (error.response?.status === 401 || error.response?.status === 403)
}
export async function refreshAccessToken(): Promise<string> {
  const expected = getSessionVersion()
  if (renewal?.version === expected) return renewal.promise
  const session = readSession()
  if (!session?.refreshToken) {
    clearSession(expected)
    throw new Error('登录已过期，请重新登录')
  }
  const promise = (async () => {
    try {
      const response = await axios.post<TokenResponse>('/api/v1/auth/refresh', { refresh_token: session.refreshToken })
      if (!isCurrentSession(expected) || readSession()?.refreshToken !== session.refreshToken) throw new SessionChangedError()
      saveSession(response.data, expected)
      return response.data.access_token
    } catch (error) {
      if (isInvalidSessionError(error) && readSession()?.refreshToken === session.refreshToken) clearSession(expected)
      throw error
    }
  })()
  renewal = { version: expected, promise }
  try { return await promise } finally {
    if (renewal?.promise === promise) renewal = null
  }
}

/** Browser WS handshakes cannot attach HTTP headers; get a current access JWT first. */
export async function ensureAccessToken(): Promise<string | null> {
  const token = getAccessToken()
  if (!token) return null
  try {
    const payload = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
    const { exp } = JSON.parse(atob(payload))
    if (typeof exp === 'number' && exp * 1000 <= Date.now() + 30000) return refreshAccessToken()
  } catch { /* Legacy/unreadable tokens are validated by the server. */ }
  return token
}

interface SessionRequest extends InternalAxiosRequestConfig {
  _sessionVersion?: number
  _accessToken?: string | null
  _authRetry?: boolean
}
const isApiRequest = (url = '') => /^\/api\/v1(?:\/|$)/.test(url)
const isAuthAction = (url = '') => /^\/api\/v1\/auth\/(login|register|refresh|logout)(?:\?|$)/.test(url)
const isProfileRequest = (url = '') => /^\/api\/v1\/auth\/me(?:\?|$)/.test(url)

/** Return an eject function so StrictMode and provider remounts cannot duplicate retries. */
export function installAuthInterceptors() {
  const onStorage = (event: StorageEvent) => {
    if (event.key === STORAGE_KEY || event.key === null) {
      synchronizeSession()
      notify()
    }
  }
  if (typeof window !== 'undefined') window.addEventListener('storage', onStorage)
  const requestId = axios.interceptors.request.use(config => {
    const request = config as SessionRequest
    if (isApiRequest(config.url) && !isAuthAction(config.url)) {
      request._sessionVersion ??= getSessionVersion()
      if (!isCurrentSession(request._sessionVersion)) throw new SessionChangedError()
      request._accessToken = getAccessToken()
      if (request._accessToken) config.headers.set('Authorization', `Bearer ${request._accessToken}`)
      else config.headers.delete('Authorization')
    }
    return config
  })
  const responseId = axios.interceptors.response.use(response => {
    const request = response.config as SessionRequest
    if (request._sessionVersion !== undefined && !isCurrentSession(request._sessionVersion)) throw new SessionChangedError()
    return response
  }, async (error: unknown) => {
    if (!axios.isAxiosError(error)) throw error
    const request = error.config as SessionRequest | undefined
    if (!request || !isApiRequest(request.url) || isAuthAction(request.url)) throw error
    const expected = request._sessionVersion
    if (expected === undefined || !isCurrentSession(expected)) throw new SessionChangedError()
    const status = error.response?.status
    if (status === 403 && isProfileRequest(request.url)) clearSession(expected)
    if (status !== 401) throw error
    if (request._authRetry) { clearSession(expected); throw error }
    request._authRetry = true
    // Another request may already have renewed while this 401 was in flight.
    if (!getAccessToken() || getAccessToken() === request._accessToken) await refreshAccessToken()
    if (!isCurrentSession(expected)) throw new SessionChangedError()
    return axios.request(request)
  })
  return () => {
    if (typeof window !== 'undefined') window.removeEventListener('storage', onStorage)
    axios.interceptors.request.eject(requestId)
    axios.interceptors.response.eject(responseId)
  }
}
