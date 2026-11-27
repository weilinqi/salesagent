import axios from 'axios'

export interface FollowUpProfile {
  customer_name: string
  identity: string
  product: string
  history_summary: string
  current_progress: string
  expectation: string
}

export interface FollowUpDraft {
  profile: FollowUpProfile
  scripts: string[]
  source_text: string
}

export async function organizeFollowUp(payload: { description?: string; table_id?: string; row_id?: string }): Promise<FollowUpDraft> {
  const { data } = await axios.post<FollowUpDraft>('/api/v1/follow-ups/organize', payload)
  return data
}
