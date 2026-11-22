import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'
import { useGuide } from '../../contexts/GuideContext'
import { GUIDE_SECTIONS, isAiConversationPath } from '../../data/guideContent'
import GuideVisual from './GuideVisual'

const GUIDE_ITEM_PREFIX = 'guide-feature-'

export default function GuideCenter() {
  const { isAuthenticated, isLoading } = useAuth()
  const location = useLocation()
  const {
    isOpen, mode, sectionId, openOverview, openModule, closeGuide,
  } = useGuide()
  const [search, setSearch] = useState('')
  const contentRef = useRef<HTMLDivElement>(null)
  const currentSection = GUIDE_SECTIONS.find(section => section.id === sectionId) || null

  useEffect(() => {
    if (!isOpen) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeGuide()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [isOpen, closeGuide])

  useEffect(() => {
    if (!isOpen) setSearch('')
  }, [isOpen])

  const visibleSections = useMemo(() => {
    const term = search.trim().toLowerCase()
    if (!term) return GUIDE_SECTIONS
    return GUIDE_SECTIONS.filter(section =>
      section.title.toLowerCase().includes(term) ||
      section.summary.toLowerCase().includes(term) ||
      section.highlights.some(item => item.toLowerCase().includes(term)) ||
      section.controls.some(control => control.label.toLowerCase().includes(term) || control.description.toLowerCase().includes(term))
    )
  }, [search])

  const visibleControls = useMemo(() => {
    if (!currentSection) return []
    const term = search.trim().toLowerCase()
    if (!term) return currentSection.controls
    return currentSection.controls.filter(control =>
      control.label.toLowerCase().includes(term) || control.description.toLowerCase().includes(term)
    )
  }, [currentSection, search])

  const scrollTo = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  if (isLoading || !isAuthenticated || isAiConversationPath(location.pathname)) return null

  return (
    <>
      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-2 sm:p-5" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) closeGuide() }}>
          <section className="flex h-[94vh] w-full max-w-7xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl" role="dialog" aria-modal="true" aria-label="使用说明">
            <header className="flex flex-col gap-3 border-b border-gray-200 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-100 text-xl text-blue-700">?</div>
                <div>
                  <h2 className="text-lg font-bold text-gray-900">{mode === 'overview' ? '使用说明' : `${currentSection?.title || ''}详细说明`}</h2>
                  <p className="text-xs text-gray-500">{mode === 'overview' ? '先看整体，再进入板块查看具体功能' : '所有功能键一目了然，点击左侧目录可快速定位'}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="search"
                  value={search}
                  onChange={event => setSearch(event.target.value)}
                  placeholder="搜索功能或按钮…"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 sm:w-64"
                />
                {mode === 'module' && (
                  <button type="button" onClick={openOverview} className="whitespace-nowrap rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50">
                    总体说明
                  </button>
                )}
                <button type="button" onClick={closeGuide} aria-label="关闭使用说明" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-xl text-gray-500 hover:bg-gray-100 hover:text-gray-800">×</button>
              </div>
            </header>

            <div className="flex min-h-0 flex-1 flex-col md:flex-row">
              <aside className="max-h-36 overflow-y-auto border-b border-gray-200 bg-gray-50 p-2 md:max-h-none md:w-72 md:border-b-0 md:border-r md:p-3">
                <p className="mb-2 px-2 text-xs font-semibold uppercase tracking-wide text-gray-400">板块大纲</p>
                <div className="flex gap-2 overflow-x-auto md:block md:space-y-1 md:overflow-visible">
                  {visibleSections.map(section => {
                    const active = section.id === sectionId
                    return (
                      <div key={section.id} className="min-w-[8rem] md:min-w-0">
                        <button
                          type="button"
                          onClick={() => {
                            openModule(section)
                            setSearch('')
                          }}
                          className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm font-medium transition ${active && mode === 'module' ? 'bg-blue-100 text-blue-800' : 'text-gray-700 hover:bg-white hover:text-blue-700'}`}
                        >
                          <span>{section.icon}</span>
                          <span>{section.title}</span>
                        </button>
                        {mode === 'module' && active && (
                          <div className="ml-4 mt-1 space-y-0.5 border-l border-blue-200 pl-2">
                            {visibleControls.map((control, index) => (
                              <button
                                key={`${control.label}-${index}`}
                                type="button"
                                onClick={() => scrollTo(`${GUIDE_ITEM_PREFIX}${section.id}-${index}`)}
                                className="block w-full truncate rounded px-2 py-1 text-left text-xs text-gray-600 hover:bg-white hover:text-blue-700"
                                title={control.label}
                              >
                                {control.label}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </aside>

              <div ref={contentRef} className="min-h-0 flex-1 overflow-y-auto scroll-smooth bg-slate-50 p-4 sm:p-6">
                {mode === 'overview' ? (
                  <div className="mx-auto max-w-5xl space-y-4">
                    <section className="rounded-2xl border border-blue-200 bg-gradient-to-br from-blue-50 to-white p-5">
                      <p className="text-xs font-semibold uppercase tracking-wide text-blue-600">欢迎使用销售智能体</p>
                      <h3 className="mt-2 text-2xl font-bold text-gray-900">先掌握整体，再看具体操作</h3>
                      <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-600">
                        下面每个板块只展示最重要的功能。点击“查看详细说明”后，会打开该板块的完整功能键清单和操作示意。
                      </p>
                    </section>

                    {visibleSections.map(section => (
                      <article key={section.id} id={`guide-section-${section.id}`} className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
                        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                          <div className="flex items-start gap-3">
                            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gray-100 text-xl">{section.icon}</span>
                            <div>
                              <h3 className="text-base font-semibold text-gray-900">{section.title}</h3>
                              <p className="mt-1 text-sm text-gray-600">{section.summary}</p>
                            </div>
                          </div>
                          <button
                            type="button"
                            onClick={() => { openModule(section); setSearch('') }}
                            className="shrink-0 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-100"
                          >
                            查看详细说明
                          </button>
                        </div>
                        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                          {section.highlights.map(item => (
                            <div key={item} className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-gray-700">• {item}</div>
                          ))}
                        </div>
                      </article>
                    ))}

                    {visibleSections.length === 0 && (
                      <div className="rounded-xl bg-white p-10 text-center text-sm text-gray-500">没有找到相关功能。</div>
                    )}
                  </div>
                ) : currentSection ? (
                  <div className="mx-auto max-w-5xl space-y-5">
                    <section className="rounded-xl border border-gray-200 bg-white p-5">
                      <div className="flex items-start gap-3">
                        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-100 text-2xl">{currentSection.icon}</span>
                        <div>
                          <h3 className="text-xl font-bold text-gray-900">{currentSection.title}</h3>
                          <p className="mt-1 text-sm text-gray-600">{currentSection.summary}</p>
                        </div>
                      </div>
                      <div className="mt-4 flex flex-wrap gap-2">
                        {currentSection.workflow.map((step, index) => (
                          <span key={step} className="rounded-full bg-blue-50 px-3 py-1.5 text-xs text-blue-800">
                            {index + 1}. {step}
                          </span>
                        ))}
                      </div>
                    </section>

                    {currentSection.visual && <GuideVisual type={currentSection.visual} />}

                    <section className="rounded-xl border border-gray-200 bg-white">
                      <div className="border-b border-gray-200 px-4 py-3">
                        <h3 className="font-semibold text-gray-900">功能键清单</h3>
                        <p className="mt-1 text-xs text-gray-500">按钮、入口和自动功能都用一句话说明，完整覆盖当前板块。</p>
                      </div>
                      <div className="divide-y divide-gray-100">
                        {visibleControls.map((control, index) => {
                          const originalIndex = currentSection.controls.findIndex(item => item === control)
                          const safeIndex = originalIndex >= 0 ? originalIndex : index
                          return (
                            <div key={`${control.label}-${safeIndex}`} id={`${GUIDE_ITEM_PREFIX}${currentSection.id}-${safeIndex}`} className="grid gap-1 px-4 py-3 sm:grid-cols-[13rem_1fr] sm:gap-4">
                              <p className="text-sm font-semibold text-gray-900">{control.label}</p>
                              <p className="text-sm leading-6 text-gray-600">{control.description}</p>
                            </div>
                          )
                        })}
                      </div>
                    </section>

                    <button type="button" onClick={openOverview} className="text-sm font-medium text-blue-700 hover:underline">← 返回总体说明</button>
                  </div>
                ) : (
                  <div className="rounded-xl bg-white p-10 text-center text-sm text-gray-500">当前板块说明不存在。</div>
                )}
              </div>
            </div>
          </section>
        </div>
      )}
    </>
  )
}
