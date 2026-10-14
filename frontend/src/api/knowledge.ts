/**
 * Knowledge Base API Client
 */
import axios from 'axios'

const API_BASE = '/api/v1/knowledge'

export interface KnowledgeStats {
  total_documents: number
  total_chunks: number
  documents_by_category: Record<string, number>
  chunks_by_source: Record<string, number>
}

export interface KnowledgeDocument {
  id: string
  name: string
  category: string
  status: 'pending' | 'queued' | 'processing' | 'completed' | 'failed'
  chunk_count: number
  error?: string | null
}

export interface IngestAllResponse {
  total: number
  results: Array<{ file: string; document_id?: string; status: string; chunks?: number; error?: string }>
}

export interface SearchResult {
  id: string
  text: string
  source: string
  score: number
  metadata: Record<string, any>
}

export interface SpinQuestions {
  situation_questions: string[]
  problem_questions: string[]
  implication_questions: string[]
  need_payoff_questions: string[]
  context_used: string[]
}

const api = {
  /**
   * Get knowledge base statistics (FR-3)
   */
  async getStats(signal?: AbortSignal): Promise<KnowledgeStats> {
    const response = await axios.get(`${API_BASE}/stats`, { signal })
    return response.data
  },

  /**
   * List all documents in knowledge base
   */
  async getDocuments(signal?: AbortSignal): Promise<KnowledgeDocument[]> {
    const response = await axios.get(`${API_BASE}/documents`, { signal })
    return response.data
  },

  /**
   * Search knowledge base
   */
  async search(query: string, top_k: number = 5): Promise<{ results: SearchResult[]; total: number }> {
    const response = await axios.post(`${API_BASE}/search`, { query, top_k })
    return response.data
  },

  /**
   * Generate SPIN questions for customer context
   */
  async generateSpinQuestions(request: {
    customer_industry: string
    customer_scale: string
    pain_points: string[]
  }): Promise<SpinQuestions> {
    const response = await axios.post(`${API_BASE}/spin/questions`, request)
    return response.data
  },

  /**
   * Ingest all documents from raw data directory
   */
  async ingestAll(signal?: AbortSignal): Promise<IngestAllResponse> {
    const response = await axios.post(`${API_BASE}/ingest-all`, undefined, { signal })
    return response.data
  },

  /**
   * Ingest a single document
   */
  async ingestDocument(filePath: string, category: string): Promise<{ document_id: string; status: string }> {
    const response = await axios.post(`${API_BASE}/ingest`, { file_path: filePath, category })
    return response.data
  }
}

export default api

export interface KnowledgeMonitorState {
  documents: KnowledgeDocument[]
  stats: KnowledgeStats | null
  isLoading: boolean
  isIngesting: boolean
  loadError: string | null
  ingestNotice: string | null
  submissionErrors: string[]
  pollingPaused: boolean
}
export const initialKnowledgeState: KnowledgeMonitorState = {
  documents: [], stats: null, isLoading: false, isIngesting: false,
  loadError: null, ingestNotice: null, submissionErrors: [], pollingPaused: false,
}

function errorMessage(error: unknown) {
  if (axios.isAxiosError(error) && typeof error.response?.data?.detail === 'string') return error.response.data.detail
  return error instanceof Error ? error.message : '请求失败，请重试'
}

/** Poll only active ingestion jobs, cap a run at two minutes, and own every request/timer. */
export function createKnowledgeMonitor(onChange: (state: KnowledgeMonitorState) => void) {
  let state = { ...initialKnowledgeState }
  let active = true
  let pollingBudget = 60
  let loading = false
  let refreshRequested = false
  let timer: ReturnType<typeof setTimeout> | undefined
  const requests = new Set<AbortController>()
  const update = (changes: Partial<KnowledgeMonitorState>) => {
    if (!active) return
    state = { ...state, ...changes }
    onChange(state)
  }
  const hasActiveJobs = () => state.documents.some(document => ['queued', 'processing'].includes(document.status))
  const load = async () => {
    if (!active) return
    if (loading) { refreshRequested = true; return }
    clearTimeout(timer)
    loading = true
    update({ isLoading: true, loadError: null })
    const controller = new AbortController()
    requests.add(controller)
    let succeeded = false
    try {
      const [documents, stats] = await Promise.allSettled([api.getDocuments(controller.signal), api.getStats(controller.signal)])
      if (!active) return
      const errors: string[] = []
      if (documents.status === 'fulfilled') {
        succeeded = true
        update({ documents: documents.value })
      } else errors.push(`文档列表：${errorMessage(documents.reason)}`)
      if (stats.status === 'fulfilled') update({ stats: stats.value })
      else errors.push(`统计：${errorMessage(stats.reason)}`)
      if (errors.length) update({ loadError: errors.join('；'), pollingPaused: !succeeded && hasActiveJobs() })
    } catch (error) {
      // Retain the last known jobs when offline; a manual refresh resumes monitoring.
      update({ loadError: errorMessage(error), pollingPaused: hasActiveJobs() })
    } finally {
      controller.abort()
      requests.delete(controller)
      loading = false
      if (active) {
        update({ isLoading: false })
        if (refreshRequested) { refreshRequested = false; void load() }
        else if (succeeded && hasActiveJobs()) {
          if (pollingBudget > 0) {
            pollingBudget--
            timer = setTimeout(() => { void load() }, 2000)
          } else update({ pollingPaused: true })
        } else if (succeeded) update({ pollingPaused: false })
      }
    }
  }
  const refresh = () => {
    pollingBudget = 60
    update({ pollingPaused: false })
    return load()
  }
  return {
    refresh,
    async ingestAll() {
      if (!active || state.isIngesting) return
      const controller = new AbortController()
      requests.add(controller)
      update({ isIngesting: true, ingestNotice: null, submissionErrors: [] })
      try {
        const response = await api.ingestAll(controller.signal)
        if (!active) return
        const queuedCount = response.results.filter(result => result.status === 'queued').length
        const completedCount = response.results.filter(result => result.status === 'completed').length
        update({
          ingestNotice: `已加入队列 ${queuedCount} 个文档，已完成 ${completedCount} 个。请查看下方处理状态。`,
          submissionErrors: response.results.filter(result => result.status === 'failed').map(result => `${result.file}：${result.error || '提交失败'}`),
        })
        await refresh()
      } catch (error) {
        update({ submissionErrors: [`提交失败：${errorMessage(error)}`] })
      } finally {
        requests.delete(controller)
        update({ isIngesting: false })
      }
    },
    dispose() {
      active = false
      clearTimeout(timer)
      requests.forEach(request => request.abort())
      requests.clear()
    },
  }
}
