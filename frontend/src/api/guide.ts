import axios from 'axios'

const API_BASE = '/api/v1/guide'

export interface GuideProgress {
  overview_seen: boolean
  modules: Record<string, boolean>
}

const guideApi = {
  async getProgress(): Promise<GuideProgress> {
    const response = await axios.get(`${API_BASE}/progress`)
    return response.data
  },

  async markSeen(scope: 'overview' | 'module', moduleId?: string): Promise<GuideProgress> {
    const response = await axios.post(`${API_BASE}/seen`, {
      scope,
      module_id: scope === 'module' ? moduleId : undefined,
    })
    return response.data
  },
}

export default guideApi