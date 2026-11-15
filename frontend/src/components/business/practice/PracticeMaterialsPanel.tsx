import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import axios from 'axios'
import type { Background, PreparationProfile } from './CustomerPreparation'

type MaterialReference = { source: string; text: string }
type MaterialHistoryItem = {
  id: string
  kind: 'preparation' | 'direction' | 'conversation'
  title: string
  query?: string
  createdAt: string
  profile?: PreparationProfile
  background?: Background
  references?: MaterialReference[]
  notFound?: boolean
}

interface Props {
  sessionId?: string
  profile?: PreparationProfile
  background?: Background
  references: MaterialReference[]
  searched?: boolean
  notFound?: boolean
  searchError?: boolean
  searchQuery?: string
  updatedAt?: string
}

const PREPARATION_ID = 'pre-conversation-pdf'
const HISTORY_LIMIT = 20
const textExcerpt = (text: string) => text.length > 230 ? `${text.slice(0, 230)}…` : text

function storageKey(sessionId?: string) {
  return sessionId ? `salesagent-material-history:${sessionId}` : ''
}

function loadHistory(sessionId?: string): MaterialHistoryItem[] {
  const key = storageKey(sessionId)
  if (!key) return []
  try {
    const value = JSON.parse(sessionStorage.getItem(key) || '[]')
    return Array.isArray(value) ? value.slice(-HISTORY_LIMIT) : []
  } catch {
    return []
  }
}

function lastItem(items: MaterialHistoryItem[]) {
  return items[items.length - 1]
}

export default function PracticeMaterialsPanel({
  sessionId, profile, background, references, searched, notFound, searchError, searchQuery, updatedAt,
}: Props) {
  const [history, setHistory] = useState<MaterialHistoryItem[]>(() => loadHistory(sessionId))
  const [selectedId, setSelectedId] = useState(() => profile
    ? PREPARATION_ID : lastItem(loadHistory(sessionId))?.id || PREPARATION_ID)
  const [pinnedItem, setPinnedItem] = useState<MaterialHistoryItem | null>(null)
  const pinned = !!pinnedItem
  const pinnedRef = useRef(pinned)
  pinnedRef.current = pinned
  const [expanded, setExpanded] = useState(false)
  const [direction, setDirection] = useState('')
  const [searching, setSearching] = useState(false)
  const [searchErrorMessage, setSearchErrorMessage] = useState('')
  const [pdfUrl, setPdfUrl] = useState('')
  const [pdfLoading, setPdfLoading] = useState(false)

  const initialBackground = useMemo<Background | undefined>(() => {
    if (!profile || background) return background
    return {
      organization: profile.organization,
      sources: [],
      gaps: ['对话前未完成公开资料检索；此 PDF 只包含员工填写的信息，不代表已查到相关资料。'],
      notice: '对话前未完成公开资料检索。学校、课程、价格及规则需以可核实来源为准。',
      checked_at: new Date().toISOString(),
      search_key: [profile.organization, profile.product, profile.needs, profile.target].map(value => value.trim()).join('\n'),
    }
  }, [profile, background])

  const initialItem = useMemo<MaterialHistoryItem | null>(() => profile && initialBackground ? ({
    id: PREPARATION_ID,
    kind: 'preparation',
    title: '对话前销售资料 PDF',
    createdAt: initialBackground.checked_at || new Date().toISOString(),
    profile,
    background: initialBackground,
  }) : null, [profile, initialBackground])

  useEffect(() => {
    setHistory(loadHistory(sessionId))
    setSelectedId(profile ? PREPARATION_ID : lastItem(loadHistory(sessionId))?.id || PREPARATION_ID)
    setPinnedItem(null)
    setExpanded(false)
  }, [sessionId, profile, background])

  useEffect(() => {
    if (!initialItem) return
    setHistory(previous => {
      const withoutOld = previous.filter(item => item.id !== PREPARATION_ID)
      return [...withoutOld, initialItem].slice(-HISTORY_LIMIT)
    })
  }, [initialItem])

  useEffect(() => {
    const key = storageKey(sessionId)
    if (!key) return
    try { sessionStorage.setItem(key, JSON.stringify(history.slice(-HISTORY_LIMIT))) } catch { /* Storage can be full or disabled. */ }
  }, [history, sessionId])

  const liveItem = useMemo<MaterialHistoryItem | null>(() => references.length ? ({
    id: `conversation-${updatedAt || Date.now()}-${(searchQuery || references.map(ref => `${ref.source}:${ref.text}`).join('|')).slice(0, 72)}`,
    kind: 'conversation',
    title: searchQuery ? `对话资料：${searchQuery}` : '对话相关知识库资料',
    query: searchQuery,
    createdAt: new Date().toISOString(),
    references,
  }) : searched ? ({
    id: `conversation-search-empty-${updatedAt || Date.now()}-${searchQuery || 'unknown'}`,
    kind: 'conversation',
    title: searchError ? '知识库暂不可用' : '知识库未找到相关资料',
    query: searchQuery,
    createdAt: new Date().toISOString(),
    references: [],
    notFound: !searchError && !!notFound,
  }) : null, [references, searched, notFound, searchError, searchQuery, updatedAt])

  useEffect(() => {
    if (!liveItem) return
    setHistory(previous => {
      if (previous.some(item => item.id === liveItem.id)) return previous
      return [...previous, liveItem].slice(-HISTORY_LIMIT)
    })
    if (!pinnedRef.current) setSelectedId(liveItem.id)
  }, [liveItem])

  useEffect(() => {
    if (updatedAt && !liveItem && !pinnedRef.current) setSelectedId(PREPARATION_ID)
  }, [updatedAt, liveItem])

  const selectedItem = history.find(item => item.id === selectedId) || initialItem || lastItem(history) || null
  const currentItem = pinnedItem || (selectedId === liveItem?.id ? liveItem : selectedItem)
  const currentProfile = currentItem?.kind === 'preparation' || currentItem?.kind === 'direction' ? currentItem.profile : undefined
  const currentBackground = currentItem?.kind === 'preparation' || currentItem?.kind === 'direction' ? currentItem.background : undefined

  useEffect(() => {
    if (!expanded || !currentItem?.profile || !currentItem.background) return
    const controller = new AbortController()
    let createdUrl = ''
    setPdfUrl('')
    setPdfLoading(true)
    axios.post('/api/v1/practice/preparation/material.pdf', {
      profile: currentItem.profile,
      background: currentItem.background,
    }, { responseType: 'blob', signal: controller.signal, timeout: 30000 })
      .then(({ data }) => {
        if (controller.signal.aborted) return
        createdUrl = URL.createObjectURL(data)
        setPdfUrl(createdUrl)
      })
      .catch(error => {
        if (!controller.signal.aborted) setSearchErrorMessage(
          axios.isAxiosError(error) && error.response?.status === 422
            ? '资料档案与检索结果不匹配，请重新查询资料。'
            : 'PDF 暂时无法生成，可先查看资料摘要和来源。',
        )
      })
      .finally(() => { if (!controller.signal.aborted) setPdfLoading(false) })
    return () => {
      controller.abort()
      if (createdUrl) URL.revokeObjectURL(createdUrl)
    }
  }, [expanded, currentItem])

  async function searchMaterials(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const query = direction.trim()
    if (!query || searching) return
    if (!profile) {
      setSearchErrorMessage('当前会话没有对话前资料档案，暂时无法按机构或产品查询。')
      return
    }
    setSearching(true)
    setSearchErrorMessage('')
    try {
      const queryProfile: PreparationProfile = {
        ...profile,
        needs: [profile.needs, query].filter(Boolean).join('；'),
      }
      const { data } = await axios.post<Background>('/api/v1/practice/preparation/background', {
        organization: queryProfile.organization.trim(),
        product: queryProfile.product,
        needs: queryProfile.needs,
        target: queryProfile.target,
      }, { timeout: 45000 })
      const item: MaterialHistoryItem = {
        id: `direction-${Date.now()}`,
        kind: 'direction',
        title: query,
        query,
        createdAt: new Date().toISOString(),
        profile: queryProfile,
        background: data,
      }
      setHistory(previous => [...previous, item].slice(-HISTORY_LIMIT))
      if (!pinned) setSelectedId(item.id)
      setDirection('')
    } catch {
      setSearchErrorMessage('资料查询暂时失败，请稍后重试。')
    } finally {
      setSearching(false)
    }
  }

  function selectHistory(item: MaterialHistoryItem) {
    if (pinned) return
    setSelectedId(item.id)
    setSearchErrorMessage('')
  }

  function togglePin() {
    if (pinnedItem) {
      setPinnedItem(null)
      setSelectedId(updatedAt && !liveItem ? PREPARATION_ID : lastItem(history)?.id || selectedId)
    } else if (currentItem) {
      setPinnedItem(currentItem)
    }
  }

  const cardSummary = currentItem?.background?.insights?.[0]?.summary
    || currentItem?.references?.[0]?.text
    || currentItem?.background?.notice

  return (
    <>
      <section className="rounded-lg border border-gray-200 bg-white p-3">
        <div className="flex items-start justify-between gap-2">
          <button type="button" aria-haspopup="dialog" aria-expanded={expanded} onClick={() => { setSearchErrorMessage(''); setExpanded(true) }} className="min-w-0 flex-1 text-left">
            <h3 className="text-xs font-semibold text-gray-700">参考资料</h3>
            <p className="mt-1 truncate text-xs font-medium text-primary">
              {currentItem?.title || '尚无对话前资料，可在放大面板中查询'}
            </p>
            {cardSummary && <p className="mt-1 line-clamp-3 text-xs text-gray-600">{textExcerpt(cardSummary)}</p>}
            <span className="mt-2 inline-block text-[11px] text-primary">点击放大查看 · 查询资料 · 历史记录</span>
          </button>
          <button type="button" onClick={togglePin} aria-pressed={pinned} disabled={!currentItem}
            className={`shrink-0 rounded border px-2 py-1 text-[11px] disabled:cursor-not-allowed disabled:opacity-50 ${pinned ? 'border-amber-300 bg-amber-50 text-amber-800' : 'border-gray-200 text-gray-600 hover:bg-gray-50'}`}>
            {pinned ? '已固定' : '固定'}
          </button>
        </div>
        {currentItem?.notFound && <p className="mt-2 rounded bg-amber-50 p-2 text-xs text-amber-800">知识库未找到相关资料，不能据此承诺具体课程、价格或规则。</p>}
        {searchError && <p className="mt-2 rounded bg-amber-50 p-2 text-xs text-amber-800">知识库检索暂不可用，当前无法核实相关信息。</p>}
      </section>

      {expanded && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) setExpanded(false) }}>
        <section role="dialog" aria-modal="true" aria-labelledby="materials-title" className="flex h-[82vh] max-h-[820px] w-full max-w-6xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl">
          <header className="flex shrink-0 items-center justify-between border-b px-5 py-3">
            <div>
              <h2 id="materials-title" className="font-semibold text-gray-900">对话资料</h2>
              <p className="text-xs text-gray-500">资料固定期间，实时指导继续更新；新的查询仍会记入历史。</p>
            </div>
            <button type="button" aria-label="关闭资料面板" onClick={() => setExpanded(false)} className="rounded p-2 text-2xl leading-none text-gray-500 hover:bg-gray-100">×</button>
          </header>

          <div className="flex min-h-0 flex-1 flex-col md:flex-row">
            <main className="flex min-h-0 min-w-0 flex-1 flex-col border-b md:border-b-0 md:border-r">
              <div className="flex items-center justify-between gap-3 border-b px-4 py-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-gray-800">{currentItem?.title || '资料查询'}</p>
                  {pinned && <span className="text-[11px] text-amber-700">当前资料已固定</span>}
                </div>
                {currentItem && <button type="button" onClick={togglePin} className="shrink-0 text-xs text-primary hover:underline">
                  {pinned ? '解除固定' : '固定此资料'}
                </button>}
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto p-4">
                {currentProfile && currentBackground ? <>
                  {pdfLoading && <p role="status" className="mb-2 text-xs text-blue-600">正在生成对话前 PDF…</p>}
                  {pdfUrl && <object data={pdfUrl} type="application/pdf" aria-label="对话前销售资料 PDF" className="h-full min-h-[320px] w-full rounded border">
                    <p className="p-4 text-sm text-gray-600">浏览器无法预览 PDF。</p>
                  </object>}
                  {!pdfUrl && !pdfLoading && <MaterialSummary background={currentBackground} />}
                  {pdfUrl && <a href={pdfUrl} download="对话前销售资料.pdf" className="mt-2 inline-block text-xs text-primary hover:underline">下载 PDF</a>}
                </> : currentItem?.references?.length ? <div className="space-y-3">
                  {currentItem.references.map((reference, index) => <article key={`${reference.source}-${index}`} className="rounded border p-3">
                    <h3 className="text-xs font-medium text-gray-500">{reference.source}</h3>
                    <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-gray-800">{reference.text}</p>
                  </article>)}
                </div> : <p className="text-sm text-gray-500">尚无资料。可在下方输入你想了解的方向。</p>}
                {searchErrorMessage && <p role="alert" className="mt-3 rounded bg-amber-50 p-3 text-sm text-amber-800">{searchErrorMessage}</p>}
                {currentItem?.notFound && <p className="mt-3 rounded bg-amber-50 p-3 text-sm text-amber-800">知识库未找到相关资料，不能据此承诺具体课程、价格或规则。</p>}
              </div>

              <form onSubmit={searchMaterials} className="flex shrink-0 items-center gap-2 border-t bg-gray-50 p-3">
                <input value={direction} onChange={event => setDirection(event.target.value)} disabled={searching} maxLength={300}
                  placeholder="输入资料方向，例如：该机构初中数学课程与收费规则" className="min-w-0 flex-1 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-primary focus:outline-none" />
                <button type="submit" disabled={searching || !direction.trim()} className="shrink-0 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
                  {searching ? '查询中…' : '查询资料'}
                </button>
              </form>
            </main>

            <aside className="flex h-36 w-full shrink-0 flex-col bg-gray-50 md:h-auto md:w-64">
              <div className="border-b px-3 py-3">
                <h3 className="text-sm font-semibold text-gray-800">资料历史</h3>
                <p className="mt-1 text-[11px] text-gray-500">保存在当前对练会话中</p>
              </div>
              <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-2">
                {[...history].reverse().map(item => <button key={item.id} type="button" onClick={() => selectHistory(item)} disabled={pinned}
                  className={`w-full rounded-lg border p-2 text-left disabled:cursor-not-allowed disabled:opacity-60 ${selectedId === item.id ? 'border-primary bg-blue-50' : 'border-gray-200 bg-white hover:bg-gray-50'}`}>
                  <span className="block line-clamp-2 text-xs font-medium text-gray-800">{item.title}</span>
                  {item.query && <span className="mt-1 block line-clamp-2 text-[11px] text-gray-500">方向：{item.query}</span>}
                  <span className="mt-1 block text-[10px] text-gray-400">{new Date(item.createdAt).toLocaleString()}</span>
                </button>)}
                {history.length === 0 && <p className="p-2 text-xs text-gray-500">查询记录会显示在这里。</p>}
              </div>
            </aside>
          </div>
        </section>
      </div>}
    </>
  )
}

function MaterialSummary({ background }: { background: Background }) {
  return <div className="space-y-4">
    {background.notice && <p className="rounded bg-blue-50 p-3 text-xs leading-relaxed text-blue-800">{background.notice}</p>}
    {background.insights?.map((insight, index) => <article key={`${insight.title}-${index}`} className="rounded-lg border p-3">
      <h3 className="font-medium text-gray-900">{insight.title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-gray-700">{insight.summary}</p>
      {insight.sources.map((source, sourceIndex) => <a key={`${source.url}-${sourceIndex}`} href={source.url} target="_blank" rel="noreferrer" className="mt-2 block text-xs text-primary hover:underline">
        {source.title} · {source.publisher || '来源'}
      </a>)}
    </article>)}
    {!background.insights?.length && background.sources.map((source, index) => <article key={`${source.url}-${index}`} className="rounded-lg border p-3">
      <h3 className="font-medium text-gray-900">{source.title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-gray-700">{source.summary}</p>
      <a href={source.url} target="_blank" rel="noreferrer" className="mt-2 block text-xs text-primary hover:underline">查看来源 · {source.publisher || '来源'}</a>
    </article>)}
    {background.gaps?.map((gap, index) => <p key={index} className="text-xs text-amber-800">{gap}</p>)}
    {!background.insights?.length && !background.sources.length && <p className="text-sm text-amber-800">对话前未找到可核实资料；请勿据此承诺具体课程、价格或规则。</p>}
  </div>
}
