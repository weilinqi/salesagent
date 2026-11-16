import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import knowledgeApi, { type KnowledgeDocument, type KnowledgeSearchResponse, type SearchResult, type WebSearchResult } from '../../../api/knowledge'
import practiceApi from '../../../api/practice'
import type { PreparationProfile } from './CustomerPreparation'

type MaterialReference = { source: string; text: string }
type MaterialHistoryItem = {
  id: string
  kind: 'preparation' | 'direction' | 'conversation'
  title: string
  query?: string
  createdAt: string
  profile?: PreparationProfile
  results?: SearchResult[]
  webResults?: WebSearchResult[]
  notices?: string[]
  references?: MaterialReference[]
  documentId?: string | null
  documentName?: string
  loaded?: boolean
  savedPdf?: boolean
  notFound?: boolean
}

interface Props {
  sessionId?: string
  profile?: PreparationProfile
  references: MaterialReference[]
  searched?: boolean
  notFound?: boolean
  searchError?: boolean
  searchQuery?: string
  updatedAt?: string
}

const PREPARATION_ID = 'pre-conversation-pdf'
const HISTORY_LIMIT = 20

function storageKey(sessionId?: string) {
  return sessionId ? `salesagent-material-history:${sessionId}` : ''
}

function deletedStorageKey(sessionId?: string) {
  return sessionId ? `salesagent-material-history-deleted:${sessionId}` : ''
}

function loadDeletedIds(sessionId?: string): string[] {
  const key = deletedStorageKey(sessionId)
  if (!key) return []
  try {
    const value = JSON.parse(sessionStorage.getItem(key) || '[]')
    return Array.isArray(value) ? value.filter((id): id is string => typeof id === 'string') : []
  } catch {
    return []
  }
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

function upsertItem(items: MaterialHistoryItem[], item: MaterialHistoryItem) {
  const withoutItem = items.filter(existing => existing.id !== item.id)
  return [...withoutItem, item].slice(-HISTORY_LIMIT)
}

function profileQuery(profile: PreparationProfile) {
  return [profile.organization, profile.product, profile.target, profile.needs]
    .map(value => value.trim())
    .filter(Boolean)
    .join(' ')
}

async function matchingDocument(results: SearchResult[], signal?: AbortSignal) {
  const source = results.find(result => result.document_id) || results[0]
  if (!source) return null
  if (source.document_id) return { id: source.document_id, name: source.source }
  try {
    const documents: KnowledgeDocument[] = await knowledgeApi.getDocuments(signal)
    const document = documents.find(item => item.status === 'completed' && item.name === source.source)
    return document ? { id: document.id, name: document.name } : null
  } catch {
    return null
  }
}

export default function PracticeMaterialsPanel({
  sessionId, profile, references, searched, notFound, searchError, searchQuery, updatedAt,
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
  const [loadingPdf, setLoadingPdf] = useState(false)
  const [searchErrorMessage, setSearchErrorMessage] = useState('')
  const [pdfError, setPdfError] = useState('')
  const [pdfUrl, setPdfUrl] = useState('')
  const [activeDocumentId, setActiveDocumentId] = useState<string | null>(null)
  const [availableDocuments, setAvailableDocuments] = useState<KnowledgeDocument[]>([])
  const [documentsLoaded, setDocumentsLoaded] = useState(false)
  const [documentsLoadFailed, setDocumentsLoadFailed] = useState(false)
  const [preparationPdfStatus, setPreparationPdfStatus] = useState<'idle' | 'loading' | 'ready' | 'missing'>('idle')
  const [preparationPdfUrl, setPreparationPdfUrl] = useState('')
  const [preparationPdfName, setPreparationPdfName] = useState('对话前销售资料.pdf')

  const initialItem = useMemo<MaterialHistoryItem | null>(() => profile ? ({
    id: PREPARATION_ID,
    kind: 'preparation',
    title: '对话前资料检索',
    query: profileQuery(profile),
    createdAt: new Date().toISOString(),
    profile,
    results: [],
    webResults: [],
    loaded: false,
  }) : null, [profile])

  useEffect(() => {
    setHistory(loadHistory(sessionId))
    setSelectedId(profile ? PREPARATION_ID : lastItem(loadHistory(sessionId))?.id || PREPARATION_ID)
    setPinnedItem(null)
    setExpanded(false)
    setPreparationPdfStatus('idle')
    setPreparationPdfUrl('')
  }, [sessionId, profile])

  useEffect(() => {
    if (!initialItem) return
    if (loadDeletedIds(sessionId).includes(initialItem.id)) return
    setHistory(previous => {
      const oldItem = previous.find(item => item.id === PREPARATION_ID)
      if (oldItem && oldItem.query === initialItem.query && oldItem.loaded) return previous
      return upsertItem(previous, initialItem)
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
    loaded: true,
  }) : searched ? ({
    id: `conversation-search-empty-${updatedAt || Date.now()}-${searchQuery || 'unknown'}`,
    kind: 'conversation',
    title: searchError ? '知识库暂不可用' : '知识库未找到相关资料',
    query: searchQuery,
    createdAt: new Date().toISOString(),
    references: [],
    loaded: true,
    notFound: !searchError && !!notFound,
  }) : null, [references, searched, notFound, searchError, searchQuery, updatedAt])

  useEffect(() => {
    if (!liveItem) return
    if (loadDeletedIds(sessionId).includes(liveItem.id)) return
    setHistory(previous => previous.some(item => item.id === liveItem.id) ? previous : upsertItem(previous, liveItem))
    if (!pinnedRef.current) setSelectedId(liveItem.id)
  }, [liveItem])

  useEffect(() => {
    if (updatedAt && !liveItem && !pinnedRef.current) setSelectedId(PREPARATION_ID)
  }, [updatedAt, liveItem])

  const selectedItem = history.find(item => item.id === selectedId) || lastItem(history) || null
  const currentItem = pinnedItem || (selectedId === liveItem?.id ? liveItem : selectedItem)
  const currentDocumentId = currentItem?.documentId || null
  const activePdfDocument = availableDocuments.find(document => document.id === activeDocumentId)

  // Load the exact PDF generated by the pre-conversation preparation flow before any corpus search.
  useEffect(() => {
    if (!expanded) {
      setPreparationPdfStatus('idle')
      setPreparationPdfUrl('')
      return
    }
    if (!sessionId) {
      setPreparationPdfStatus('missing')
      return
    }
    const controller = new AbortController()
    let objectUrl = ''
    setPreparationPdfStatus('loading')
    practiceApi.getSessionPreparationPdf(sessionId, controller.signal)
      .then(({ blob, filename }) => {
        if (controller.signal.aborted) return
        objectUrl = URL.createObjectURL(blob)
        setPreparationPdfUrl(objectUrl)
        setPreparationPdfName(filename)
        setPreparationPdfStatus('ready')
        if (initialItem && !loadDeletedIds(sessionId).includes(PREPARATION_ID)) {
          setHistory(previous => upsertItem(previous, {
            ...(previous.find(item => item.id === PREPARATION_ID) || initialItem),
            title: `对话前原始 PDF：${filename}`,
            results: [],
            webResults: [],
            notices: [],
            references: undefined,
            documentId: null,
            documentName: undefined,
            loaded: true,
            savedPdf: true,
            notFound: false,
          }))
          if (!pinnedRef.current) setSelectedId(PREPARATION_ID)
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setPreparationPdfStatus('missing')
          setHistory(previous => previous.map(item => item.id === PREPARATION_ID
            ? { ...item, title: '对话前资料检索', loaded: false, savedPdf: false, documentId: null, documentName: undefined }
            : item))
        }
      })
    return () => {
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [expanded, sessionId, initialItem])

  // The first intentional open searches the existing corpus and resolves the best chunk to its original PDF.
  useEffect(() => {
    if (!expanded || !currentItem || currentItem.kind === 'conversation' || currentItem.loaded) return
    if (currentItem.kind === 'preparation' && ['idle', 'loading', 'ready'].includes(preparationPdfStatus)) return
    const query = currentItem.query || (currentItem.profile ? profileQuery(currentItem.profile) : '')
    if (!query) {
      setHistory(previous => upsertItem(previous, { ...currentItem, loaded: true, notFound: true }))
      return
    }

    const controller = new AbortController()
    setSearching(true)
    setSearchErrorMessage('')
    knowledgeApi.search(query, 8, currentItem.kind === 'preparation' ? 'local' : 'auto', controller.signal)
      .then(async (response: KnowledgeSearchResponse) => {
        if (controller.signal.aborted) return
        const source = await matchingDocument(response.results, controller.signal)
        if (controller.signal.aborted) return
        const refreshed: MaterialHistoryItem = {
          ...currentItem,
          title: currentItem.kind === 'preparation' && source ? `对话前原始 PDF：${source.name}`
            : currentItem.kind === 'preparation' ? '对话前资料检索' : currentItem.title,
          query,
          results: response.results,
          webResults: response.web_results || [],
          notices: response.notices || [],
          documentId: source?.id || null,
          documentName: source?.name,
          loaded: true,
          notFound: response.results.length === 0 && (response.web_results || []).length === 0,
        }
        setHistory(previous => upsertItem(previous, refreshed))
        setPinnedItem(previous => previous?.id === refreshed.id ? refreshed : previous)
        if (!pinnedRef.current) setSelectedId(refreshed.id)
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setSearchErrorMessage('知识库搜索暂时失败，请稍后重试。')
          setHistory(previous => upsertItem(previous, { ...currentItem, loaded: true, notFound: true }))
        }
      })
      .finally(() => { if (!controller.signal.aborted) setSearching(false) })
    return () => controller.abort()
  }, [expanded, currentItem?.id, currentItem?.loaded, preparationPdfStatus])

  useEffect(() => {
    setActiveDocumentId(currentDocumentId)
  }, [currentItem?.id, currentDocumentId])

  useEffect(() => {
    if (!expanded) return
    const controller = new AbortController()
    setDocumentsLoaded(false)
    setDocumentsLoadFailed(false)
    knowledgeApi.getDocuments(controller.signal)
      .then(documents => {
        if (controller.signal.aborted) return
        setAvailableDocuments(documents.filter(document => document.source_type === 'pdf'))
        setDocumentsLoaded(true)
      })
      .catch(() => {
        if (controller.signal.aborted) return
        setAvailableDocuments([])
        setDocumentsLoadFailed(true)
        setDocumentsLoaded(true)
      })
    return () => controller.abort()
  }, [expanded, sessionId])

  useEffect(() => {
    if (!expanded || !activeDocumentId) {
      setPdfUrl('')
      setPdfError('')
      setLoadingPdf(false)
      return
    }
    const controller = new AbortController()
    let createdUrl = ''
    setPdfUrl('')
    setPdfError('')
    setLoadingPdf(true)
    knowledgeApi.getOriginalPdf(activeDocumentId, controller.signal)
      .then(blob => {
        if (controller.signal.aborted) return
        createdUrl = URL.createObjectURL(blob)
        setPdfUrl(createdUrl)
      })
      .catch(() => {
        if (!controller.signal.aborted) setPdfError('原始 PDF 暂时无法读取，请检查文档是否仍在知识库目录中。')
      })
      .finally(() => { if (!controller.signal.aborted) setLoadingPdf(false) })
    return () => {
      controller.abort()
      if (createdUrl) URL.revokeObjectURL(createdUrl)
    }
  }, [expanded, activeDocumentId])

  async function searchMaterials(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const query = direction.trim()
    if (!query || searching) return
    const item: MaterialHistoryItem = {
      id: `direction-${Date.now()}`,
      kind: 'direction',
      title: query,
      query,
      createdAt: new Date().toISOString(),
      results: [],
      loaded: true,
    }
    setHistory(previous => upsertItem(previous, item))
    if (!pinned) setSelectedId(item.id)
    setDirection('')
    setSearching(true)
    setSearchErrorMessage('')
    try {
      const response = await knowledgeApi.search(query, 8, 'auto')
      const source = await matchingDocument(response.results)
      const result: MaterialHistoryItem = {
        ...item,
        results: response.results,
        webResults: response.web_results || [],
        notices: response.notices || [],
        documentId: source?.id || null,
        documentName: source?.name,
        notFound: response.results.length === 0 && (response.web_results || []).length === 0,
      }
      setHistory(previous => upsertItem(previous, result))
    } catch {
      setSearchErrorMessage('资料查询暂时失败，请稍后重试。')
      setHistory(previous => upsertItem(previous, { ...item, notFound: true }))
    } finally {
      setSearching(false)
    }
  }

  function selectHistory(item: MaterialHistoryItem) {
    if (pinned) return
    setSelectedId(item.id)
    setSearchErrorMessage('')
  }

  function deleteHistory(itemId: string) {
    const remaining = history.filter(item => item.id !== itemId)
    const deletedKey = deletedStorageKey(sessionId)
    if (deletedKey) {
      const deletedIds = loadDeletedIds(sessionId)
      if (!deletedIds.includes(itemId)) {
        try { sessionStorage.setItem(deletedKey, JSON.stringify([...deletedIds, itemId].slice(-HISTORY_LIMIT * 4))) } catch { /* Storage can be disabled. */ }
      }
    }
    setHistory(remaining)
    if (pinnedItem?.id === itemId) setPinnedItem(null)
    if (selectedId === itemId) {
      const next = lastItem(remaining)
      setSelectedId(next?.id || '')
    }
  }

  function togglePin() {
    if (pinnedItem) {
      setPinnedItem(null)
      setSelectedId(updatedAt && !liveItem ? PREPARATION_ID : lastItem(history)?.id || selectedId)
    } else if (currentItem) {
      setPinnedItem(currentItem)
    }
  }

  return (
    <>
      <button type="button" aria-haspopup="dialog" aria-expanded={expanded}
        onClick={() => { setSearchErrorMessage(''); if (profile) setSelectedId(loadDeletedIds(sessionId).includes(PREPARATION_ID) ? lastItem(history)?.id || '' : PREPARATION_ID); setExpanded(true) }}
        className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-orange-500 px-3 py-1.5 text-xs font-semibold text-white shadow-sm transition hover:bg-orange-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-600">
        <span aria-hidden="true">▤</span>
        <span>资料</span>
        {pinned && <span className="rounded bg-white/20 px-1">已固定</span>}
      </button>

      {expanded && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) setExpanded(false) }}>
        <section role="dialog" aria-modal="true" aria-labelledby="materials-title" className="flex h-[82vh] max-h-[820px] w-full max-w-6xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl">
          <header className="flex shrink-0 items-center justify-between border-b px-5 py-3">
            <div>
              <h2 id="materials-title" className="font-semibold text-gray-900">对话资料</h2>
              <p className="text-xs text-gray-500">默认先显示本次对话前生成并保存的 PDF；对话和主动查询展示知识库原文及出处。</p>
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
                {(searching || loadingPdf) && <p role="status" className="mb-3 text-xs text-blue-600">{searching ? '正在检索知识库资料…' : '正在打开原始 PDF…'}</p>}
                {preparationPdfStatus === 'loading' && currentItem?.kind === 'preparation' && <p role="status" className="mb-3 text-xs text-blue-600">正在读取本次对话前生成并保存的 PDF…</p>}
                {searchErrorMessage && <p role="alert" className="mb-3 rounded bg-amber-50 p-3 text-sm text-amber-800">{searchErrorMessage}</p>}
                {pdfError && <p role="alert" className="mb-3 rounded bg-amber-50 p-3 text-sm text-amber-800">{pdfError}</p>}
                {preparationPdfUrl && currentItem?.kind === 'preparation' && <section className="mb-5 rounded-lg border border-primary/30 bg-blue-50/30 p-3">
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <h3 className="truncate text-sm font-semibold text-gray-800">本次对话前资料：{preparationPdfName}</h3>
                    <a href={preparationPdfUrl} download={preparationPdfName} className="shrink-0 text-xs text-primary hover:underline">下载原件</a>
                  </div>
                  <object data={preparationPdfUrl} type="application/pdf" aria-label="本次对话前生成的原始 PDF" className="h-[50vh] min-h-[320px] w-full rounded border">
                    <p className="p-4 text-sm text-gray-600">浏览器无法预览 PDF，请下载原件查看。</p>
                  </object>
                </section>}
                {availableDocuments.length > 0 && <label className="mb-3 flex items-center gap-2 text-xs text-gray-600">
                  <span className="shrink-0">原始 PDF</span>
                  <select value={activeDocumentId || ''} onChange={event => setActiveDocumentId(event.target.value || null)} className="min-w-0 flex-1 rounded border border-gray-300 bg-white px-2 py-1.5 text-xs">
                    <option value="">选择已上传的 PDF</option>
                    {availableDocuments.map(document => <option key={document.id} value={document.id}>{document.name}</option>)}
                  </select>
                </label>}
                {pdfUrl && <section className="mb-5 rounded-lg border p-3">
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <h3 className="truncate text-sm font-semibold text-gray-800">原始 PDF：{activePdfDocument?.name || currentItem?.documentName || currentItem?.title}</h3>
                    <a href={pdfUrl} download={activePdfDocument?.name || currentItem?.documentName || '知识库原始资料.pdf'} className="shrink-0 text-xs text-primary hover:underline">下载原件</a>
                  </div>
                  <object data={pdfUrl} type="application/pdf" aria-label="知识库原始 PDF" className="h-[50vh] min-h-[320px] w-full rounded border">
                    <p className="p-4 text-sm text-gray-600">浏览器无法预览 PDF，请下载原件查看。</p>
                  </object>
                </section>}
                {currentItem?.results?.map(result => <KnowledgeExcerpt key={result.id} result={result}
                  onOpenPdf={result.document_id ? () => setActiveDocumentId(result.document_id!) : undefined} />)}
                {currentItem?.references?.map((reference, index) => <article key={`${reference.source}-${index}`} className="mb-3 rounded-lg border p-3">
                  <h3 className="text-xs font-semibold text-gray-500">对话参考：{reference.source}</h3>
                  <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-gray-800">{reference.text}</p>
                </article>)}
                {currentItem?.webResults?.map((result, index) => <article key={`${result.url}-${index}`} className="mb-3 rounded-lg border border-blue-100 bg-blue-50/40 p-3">
                  <h3 className="text-sm font-medium text-gray-800">公开网页：{result.title || '搜索结果'}</h3>
                  <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-gray-700">{result.snippet || '网页搜索未返回摘要。'}</p>
                  <a href={result.url} target="_blank" rel="noreferrer" className="mt-2 block break-all text-xs text-primary hover:underline">查看来源原文{result.date ? ` · ${result.date}` : ''}</a>
                </article>)}
                {currentItem?.notices?.map((notice, index) => <p key={index} className="mb-2 rounded bg-amber-50 p-3 text-xs text-amber-800">{notice}</p>)}
                {documentsLoaded && availableDocuments.length === 0 && preparationPdfStatus !== 'ready' && <p className="mb-3 rounded bg-amber-50 p-3 text-sm text-amber-800">
                  {documentsLoadFailed ? '无法读取知识库文档列表，请检查登录状态或后端连接。' : '当前后端知识库没有登记可预览的原始 PDF。请将同事上传的 PDF 放入后端知识库目录并导入；文件不会随 Git 合并。'}
                </p>}
                {currentItem?.notFound && !searching && <p className="rounded bg-amber-50 p-3 text-sm text-amber-800">知识库和公开搜索均未找到可核实资料；请调整关键词或补充原始 PDF。</p>}
                {!searching && currentItem?.kind === 'preparation' && !currentItem.results?.length && !currentItem.notFound && !currentItem.references?.length && <p className="text-sm text-gray-500">打开资料面板后会按本次对练信息检索已入库原始 PDF。</p>}
                {!searching && currentItem?.kind === 'preparation' && currentItem.loaded && !currentItem.documentId && !!currentItem.results?.length && <p className="mb-3 rounded bg-amber-50 p-3 text-sm text-amber-800">已找到知识片段，但没有对应的原始 PDF 文件记录；下方仍可查看完整检索内容。</p>}
                {!currentItem && <p className="text-sm text-gray-500">当前会话没有准备资料。可在下方输入资料方向进行检索。</p>}
              </div>

              <form onSubmit={searchMaterials} className="flex shrink-0 items-center gap-2 border-t bg-gray-50 p-3">
                <input value={direction} onChange={event => setDirection(event.target.value)} disabled={searching} maxLength={300}
                  placeholder="输入资料方向，例如：上海某机构初中数学课程、价格或规则" className="min-w-0 flex-1 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-primary focus:outline-none" />
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
                {[...history].reverse().map(item => <div key={item.id}
                  className={`flex items-start gap-1 rounded-lg border p-2 ${selectedId === item.id ? 'border-primary bg-blue-50' : 'border-gray-200 bg-white'}`}>
                  <button type="button" onClick={() => selectHistory(item)} disabled={pinned}
                    className="min-w-0 flex-1 text-left disabled:cursor-not-allowed disabled:opacity-60">
                    <span className="block line-clamp-2 text-xs font-medium text-gray-800">{item.title}</span>
                    {item.query && <span className="mt-1 block line-clamp-2 text-[11px] text-gray-500">方向：{item.query}</span>}
                    <span className="mt-1 block text-[10px] text-gray-400">{new Date(item.createdAt).toLocaleString()}</span>
                  </button>
                  <button type="button" aria-label={`删除资料历史：${item.title}`} title="删除记录"
                    onClick={() => deleteHistory(item.id)}
                    className="shrink-0 rounded p-1 text-gray-400 hover:bg-red-50 hover:text-red-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-red-500">
                    <span aria-hidden="true">×</span>
                  </button>
                </div>)}
                {history.length === 0 && <p className="p-2 text-xs text-gray-500">查询记录会显示在这里。</p>}
              </div>
            </aside>
          </div>
        </section>
      </div>}
    </>
  )
}

function KnowledgeExcerpt({ result, onOpenPdf }: { result: SearchResult; onOpenPdf?: () => void }) {
  const details = [
    typeof result.metadata?.chapter === 'string' && result.metadata.chapter,
    typeof result.metadata?.section === 'string' && result.metadata.section,
    result.metadata?.page != null && `第 ${result.metadata.page} 页`,
  ].filter(Boolean).join(' · ')
  return <article className="mb-3 rounded-lg border p-3">
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <h3 className="text-xs font-semibold text-gray-500">知识库原文 · {result.source}</h3>
        {details && <p className="mt-1 text-[11px] text-gray-400">{details}</p>}
      </div>
      {onOpenPdf && <button type="button" onClick={onOpenPdf} className="shrink-0 text-xs text-primary hover:underline">打开原始 PDF</button>}
    </div>
    <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-gray-800">{result.text}</p>
  </article>
}
