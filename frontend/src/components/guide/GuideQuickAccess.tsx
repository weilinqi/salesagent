import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { useLocation } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'
import { useGuide } from '../../contexts/GuideContext'
import { isAiConversationPath, sectionForPath } from '../../data/guideContent'

const GUIDE_BUTTON_WIDTH = 164
const GUIDE_BUTTON_HEIGHT = 58
const GUIDE_EDGE_GAP = 12
const GUIDE_TOP_SAFE_AREA = 92
const GUIDE_BOTTOM_SAFE_AREA = 96
const GUIDE_POSITION_KEY = 'salesagent-guide-floating-position-v2'

interface GuidePosition {
  x: number
  y: number
}

interface DragState {
  pointerId: number | null
  startX: number
  startY: number
  originX: number
  originY: number
  moved: boolean
  suppressClick: boolean
}

function useGuideQuickAccess() {
  const { isAuthenticated, isLoading } = useAuth()
  const { isOpen, openCurrentModule } = useGuide()
  const location = useLocation()
  const pageSection = sectionForPath(location.pathname)
  const hidden = isAiConversationPath(location.pathname)

  return {
    pageSection,
    available: !hidden && !isLoading && isAuthenticated && !isOpen && Boolean(pageSection),
    openCurrentModule,
  }
}

function clampGuidePosition(position: GuidePosition): GuidePosition {
  const maxX = Math.max(GUIDE_EDGE_GAP, window.innerWidth - GUIDE_BUTTON_WIDTH - GUIDE_EDGE_GAP)
  const maxY = Math.max(GUIDE_TOP_SAFE_AREA, window.innerHeight - GUIDE_BUTTON_HEIGHT - GUIDE_BOTTOM_SAFE_AREA)

  return {
    x: Math.min(maxX, Math.max(GUIDE_EDGE_GAP, position.x)),
    y: Math.min(maxY, Math.max(GUIDE_TOP_SAFE_AREA, position.y)),
  }
}

function defaultGuidePosition(): GuidePosition {
  return clampGuidePosition({
    x: window.innerWidth - GUIDE_BUTTON_WIDTH - GUIDE_EDGE_GAP,
    y: Math.max(GUIDE_TOP_SAFE_AREA, Math.round(window.innerHeight * 0.28)),
  })
}

function readGuidePosition(): GuidePosition | null {
  try {
    const stored = localStorage.getItem(GUIDE_POSITION_KEY)
    if (!stored) return null
    const parsed = JSON.parse(stored) as Partial<GuidePosition>
    if (typeof parsed.x !== 'number' || typeof parsed.y !== 'number') return null
    return clampGuidePosition({ x: parsed.x, y: parsed.y })
  } catch {
    return null
  }
}

function saveGuidePosition(position: GuidePosition) {
  try {
    localStorage.setItem(GUIDE_POSITION_KEY, JSON.stringify(position))
  } catch {
    return
  }
}

export function GuideFloatingButton() {
  const { pageSection, available, openCurrentModule } = useGuideQuickAccess()
  const [position, setPosition] = useState<GuidePosition | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const positionRef = useRef<GuidePosition | null>(null)
  const dragState = useRef<DragState>({
    pointerId: null,
    startX: 0,
    startY: 0,
    originX: 0,
    originY: 0,
    moved: false,
    suppressClick: false,
  })

  useEffect(() => {
    const updatePosition = () => {
      setPosition(current => clampGuidePosition(current ?? readGuidePosition() ?? defaultGuidePosition()))
    }

    updatePosition()
    window.addEventListener('resize', updatePosition)
    return () => window.removeEventListener('resize', updatePosition)
  }, [])

  useEffect(() => {
    positionRef.current = position
  }, [position])

  if (!pageSection || !available) return null

  const handlePointerDown = (event: ReactPointerEvent<HTMLButtonElement>) => {
    if (!position || (event.pointerType === 'mouse' && event.button !== 0)) return

    dragState.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: position.x,
      originY: position.y,
      moved: false,
      suppressClick: false,
    }
    event.currentTarget.setPointerCapture(event.pointerId)
    setIsDragging(true)
  }

  const handlePointerMove = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const state = dragState.current
    if (state.pointerId !== event.pointerId) return

    const next = clampGuidePosition({
      x: state.originX + event.clientX - state.startX,
      y: state.originY + event.clientY - state.startY,
    })

    if (Math.hypot(event.clientX - state.startX, event.clientY - state.startY) > 5) {
      state.moved = true
    }

    positionRef.current = next
    setPosition(next)
  }

  const handlePointerEnd = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const state = dragState.current
    if (state.pointerId !== event.pointerId) return

    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    setIsDragging(false)

    const current = positionRef.current ?? position
    if (state.moved && current) {
      const snapped = clampGuidePosition({
        x: current.x + GUIDE_BUTTON_WIDTH / 2 < window.innerWidth / 2
          ? GUIDE_EDGE_GAP
          : window.innerWidth - GUIDE_BUTTON_WIDTH - GUIDE_EDGE_GAP,
        y: current.y,
      })
      positionRef.current = snapped
      setPosition(snapped)
      saveGuidePosition(snapped)
      state.suppressClick = true
      window.setTimeout(() => {
        dragState.current.suppressClick = false
      }, 0)
    }

    state.pointerId = null
  }

  const handlePointerCancel = () => {
    dragState.current.pointerId = null
    setIsDragging(false)
  }

  const handleClick = () => {
    if (dragState.current.suppressClick) {
      dragState.current.suppressClick = false
      return
    }
    openCurrentModule()
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerEnd}
      onPointerCancel={handlePointerCancel}
      className={`fixed z-40 flex touch-none select-none items-center gap-2 rounded-full border-2 border-blue-500 bg-blue-600 px-3 text-white shadow-xl transition-[box-shadow,transform,background-color] ${
        isDragging ? 'scale-[1.03] cursor-grabbing shadow-2xl ring-4 ring-blue-300/60' : 'cursor-grab hover:-translate-y-0.5 hover:bg-blue-700 hover:shadow-2xl'
      }`}
      style={{
        width: GUIDE_BUTTON_WIDTH,
        height: GUIDE_BUTTON_HEIGHT,
        left: position?.x ?? GUIDE_EDGE_GAP,
        top: position?.y ?? GUIDE_TOP_SAFE_AREA,
        visibility: position ? 'visible' : 'hidden',
      }}
      aria-label={`拖动或点击打开${pageSection.title}使用说明`}
      title={`点击查看说明，按住可拖动 · ${pageSection.title}`}
    >
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white text-lg font-bold text-blue-700 shadow-sm">?</span>
      <span className="min-w-0 flex-1 text-left leading-tight">
        <span className="block whitespace-nowrap text-sm font-bold">使用说明</span>
        <span className="block truncate text-[11px] font-medium text-blue-100">{pageSection.title}</span>
      </span>
      <svg className="h-4 w-4 shrink-0 text-blue-200" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="9" cy="7" r="1.5" />
        <circle cx="15" cy="7" r="1.5" />
        <circle cx="9" cy="12" r="1.5" />
        <circle cx="15" cy="12" r="1.5" />
        <circle cx="9" cy="17" r="1.5" />
        <circle cx="15" cy="17" r="1.5" />
      </svg>
    </button>
  )
}
