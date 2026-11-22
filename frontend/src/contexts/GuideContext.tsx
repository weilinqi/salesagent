import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import guideApi, { GuideProgress } from '../api/guide'
import { useAuth } from './AuthContext'
import { GuideSection, isAiConversationPath, sectionForPath } from '../data/guideContent'

type GuideMode = 'overview' | 'module'

interface GuideState {
  mode: GuideMode
  sectionId: string | null
}

interface GuideContextValue {
  isOpen: boolean
  mode: GuideMode
  sectionId: string | null
  progress: GuideProgress | null
  openOverview: () => void
  openModule: (section: GuideSection) => void
  openCurrentModule: () => void
  closeGuide: () => void
  goOverview: () => void
}

const GuideContext = createContext<GuideContextValue | null>(null)
const autoOpenedThisLoad = new Set<string>()

export function GuideProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading, user } = useAuth()
  const location = useLocation()
  const [progress, setProgress] = useState<GuideProgress | null>(null)
  const [guide, setGuide] = useState<GuideState | null>(null)
  const progressLoaded = useRef(false)
  const currentSection = sectionForPath(location.pathname)

  const markSeen = useCallback(async (scope: GuideMode, moduleId?: string) => {
    if (!isAuthenticated) return
    try {
      const next = await guideApi.markSeen(scope, moduleId)
      setProgress(next)
    } catch {
      // The guide remains usable even if progress persistence is temporarily unavailable.
    }
  }, [isAuthenticated])

  const openOverview = useCallback(() => {
    setGuide({ mode: 'overview', sectionId: null })
    if (!progress?.overview_seen) void markSeen('overview')
  }, [markSeen, progress?.overview_seen])

  const openModule = useCallback((section: GuideSection) => {
    setGuide({ mode: 'module', sectionId: section.id })
    if (!progress?.modules?.[section.id]) void markSeen('module', section.id)
  }, [markSeen, progress?.modules])

  const openCurrentModule = useCallback(() => {
    if (currentSection) openModule(currentSection)
    else openOverview()
  }, [currentSection, openModule, openOverview])

  const closeGuide = useCallback(() => setGuide(null), [])
  const goOverview = useCallback(() => setGuide({ mode: 'overview', sectionId: null }), [])

  useEffect(() => {
    if (isAiConversationPath(location.pathname)) setGuide(null)
  }, [location.pathname])

  useEffect(() => {
    if (isLoading) return
    if (!isAuthenticated || !user?.id) {
      progressLoaded.current = false
      setProgress(null)
      setGuide(null)
      return
    }
    if (progressLoaded.current) return
    progressLoaded.current = true
    let active = true
    guideApi.getProgress().then(data => {
      if (!active) return
      setProgress(data)
      const overviewKey = `overview:${user.id}`
      if (!data.overview_seen && !autoOpenedThisLoad.has(overviewKey)) {
        autoOpenedThisLoad.add(overviewKey)
        setGuide({ mode: 'overview', sectionId: null })
        void guideApi.markSeen('overview').then(next => { if (active) setProgress(next) }).catch(() => undefined)
      }
    }).catch(() => {
      if (active) progressLoaded.current = false
    })
    return () => { active = false }
  }, [isAuthenticated, isLoading, user?.id])

  useEffect(() => {
    if (isLoading || !isAuthenticated || !progress || guide) return
    if (isAiConversationPath(location.pathname)) return
    if (location.pathname === '/dashboard' || location.pathname === '/') return
    if (!currentSection || progress.modules?.[currentSection.id]) return
    const key = `module:${user?.id}:${currentSection.id}`
    if (autoOpenedThisLoad.has(key)) return
    autoOpenedThisLoad.add(key)
    setGuide({ mode: 'module', sectionId: currentSection.id })
    void guideApi.markSeen('module', currentSection.id).then(setProgress).catch(() => undefined)
  }, [isAuthenticated, isLoading, progress, guide, location.pathname, currentSection, user?.id])

  return (
    <GuideContext.Provider value={{
      isOpen: Boolean(guide),
      mode: guide?.mode || 'overview',
      sectionId: guide?.sectionId || null,
      progress,
      openOverview,
      openModule,
      openCurrentModule,
      closeGuide,
      goOverview,
    }}>
      {children}
    </GuideContext.Provider>
  )
}

export function useGuide() {
  const context = useContext(GuideContext)
  if (!context) throw new Error('useGuide must be used within GuideProvider')
  return context
}
