import { createContext, useContext, useState, useEffect, ReactNode, useCallback } from 'react'
import authApi, { User } from '../api/auth'
import {
  clearSession, getAccessToken, getSessionVersion, installAuthInterceptors,
  isCurrentSession, readSession, saveSession, saveSessionUser, subscribeSession,
} from '../api/session'

interface AuthState {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  sessionError?: string | null
}
interface AuthContextType extends AuthState {
  login: (email: string, password: string) => Promise<void>
  register: (email: string, username: string, password: string, fullName?: string) => Promise<void>
  logout: () => Promise<void>
  updateUser: (updates: Partial<User>) => void
  refreshUser: () => Promise<void>
  getAccessToken: () => string | null
}
const AuthContext = createContext<AuthContextType | null>(null)
const snapshot = (): AuthState => {
  const session = readSession()
  return { user: session?.user || null, isAuthenticated: !!session, isLoading: false, sessionError: null }
}

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [authState, setAuthState] = useState<AuthState>({ user: null, isAuthenticated: false, isLoading: true })

  const refreshUser = useCallback(async () => {
    const expected = getSessionVersion()
    if (!readSession()) { setAuthState(snapshot()); return }
    try {
      const user = await authApi.me()
      if (isCurrentSession(expected)) { saveSessionUser(user, expected); setAuthState(snapshot()) }
    } catch {
      if (!isCurrentSession(expected)) return
      setAuthState({ ...snapshot(), sessionError: '暂时无法验证登录状态，请检查网络后重试。' })
    }
  }, [])

  useEffect(() => {
    let active = true
    const eject = installAuthInterceptors()
    const unsubscribe = subscribeSession(() => { if (active) setAuthState(snapshot()) })
    const expected = getSessionVersion()
    const stored = readSession()
    setAuthState({ ...snapshot(), isLoading: !!stored })
    if (stored) {
      authApi.me().then(user => {
        if (active && isCurrentSession(expected)) { saveSessionUser(user, expected); setAuthState(snapshot()) }
      }).catch(() => {
        if (active && isCurrentSession(expected)) {
          setAuthState({ ...snapshot(), sessionError: '暂时无法验证登录状态，请检查网络后重试。' })
        }
      })
    }
    return () => { active = false; unsubscribe(); eject() }
  }, [])

  const login = async (email: string, password: string) => {
    clearSession()
    const expected = getSessionVersion()
    const response = await authApi.login({ email, password })
    saveSession(response, expected)
  }
  const register = async (email: string, username: string, password: string, fullName?: string) => {
    clearSession()
    const expected = getSessionVersion()
    const response = await authApi.register({ email, username, password, full_name: fullName })
    saveSession(response, expected)
  }
  const logout = async () => {
    // Invalidate pending work immediately, before waiting for the server.
    const token = getAccessToken()
    clearSession()
    try { await authApi.logout(token) } catch { /* Local sign-out is already complete. */ }
  }
  const updateUser = (updates: Partial<User>) => {
    const session = readSession()
    if (session) saveSessionUser({ ...session.user, ...updates }, getSessionVersion())
  }

  return (
    <AuthContext.Provider value={{ ...authState, login, register, logout, updateUser, refreshUser, getAccessToken }}>
      {authState.sessionError && (
        <div role="alert" className="flex items-center justify-center gap-3 bg-amber-50 p-3 text-sm text-amber-900">
          <span>{authState.sessionError}</span>
          <button type="button" className="underline" onClick={() => { void refreshUser() }}>重试</button>
        </div>
      )}
      {children}
    </AuthContext.Provider>
  )
}
export const useAuth = () => {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within AuthProvider')
  return context
}
