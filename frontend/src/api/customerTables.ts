import axios from 'axios'

const API_BASE = '/api/v1/customer-tables'

export interface CustomerColumn {
  key: string
  label: string
  source_header?: string | null
  semantic_type: string
  confidence: number
}

export interface UncertainItem {
  column_key: string
  label: string
  value: string
  reason: string
  reviewed: boolean
}

export interface CustomerRow {
  id: string
  position: number
  cells: Record<string, string>
  original_cells: Record<string, string>
  uncertain: UncertainItem[]
}

export interface CustomerTableSummary {
  id: string
  name: string
  source_filename?: string | null
  source_sheet?: string | null
  header_row?: number | null
  columns: CustomerColumn[]
  row_count: number
  uncertain_count: number
  created_at: string
  updated_at: string
}

export interface CustomerTableDetail extends CustomerTableSummary {
  rows: CustomerRow[]
  total: number
  page: number
  page_size: number
}

export interface RowUpdatePayload {
  cells?: Record<string, string>
  confirm_keys?: string[]
  confirm_all?: boolean
}

export interface BatchConfirmResponse {
  confirmed_count: number
  remaining_count: number
}

export interface BatchDeleteResponse {
  deleted_count: number
  remaining_rows: number
}

const api = {
  async listTables(): Promise<CustomerTableSummary[]> {
    const response = await axios.get(API_BASE)
    return response.data
  },

  async importTable(file: File): Promise<CustomerTableDetail> {
    const form = new FormData()
    form.append('file', file)
    const response = await axios.post(`${API_BASE}/import`, form)
    return response.data
  },

  async getTable(
    tableId: string,
    page = 1,
    pageSize = 50,
    search = '',
  ): Promise<CustomerTableDetail> {
    const response = await axios.get(`${API_BASE}/${tableId}`, {
      params: { page, page_size: pageSize, search },
    })
    return response.data
  },

  async updateRow(
    tableId: string,
    rowId: string,
    payload: RowUpdatePayload,
  ): Promise<CustomerRow> {
    const response = await axios.patch(`${API_BASE}/${tableId}/rows/${rowId}`, payload)
    return response.data
  },

  async deleteRow(tableId: string, rowId: string): Promise<void> {
    await axios.delete(`${API_BASE}/${tableId}/rows/${rowId}`)
  },

  async confirmAllUncertain(tableId: string): Promise<BatchConfirmResponse> {
    const response = await axios.post(`${API_BASE}/${tableId}/uncertain/confirm-all`)
    return response.data
  },

  async deleteRows(tableId: string, rowIds: string[]): Promise<BatchDeleteResponse> {
    const response = await axios.post(`${API_BASE}/${tableId}/rows/batch-delete`, { row_ids: rowIds })
    return response.data
  },

  async addRow(tableId: string): Promise<CustomerRow> {
    const response = await axios.post(`${API_BASE}/${tableId}/rows`, { cells: {} })
    return response.data
  },

  async addColumn(
    tableId: string,
    label: string,
    semanticType = 'text',
  ): Promise<CustomerTableDetail> {
    const response = await axios.post(`${API_BASE}/${tableId}/columns`, {
      label,
      semantic_type: semanticType,
    })
    return response.data
  },

  async renameColumn(
    tableId: string,
    columnKey: string,
    label: string,
  ): Promise<CustomerTableSummary> {
    const response = await axios.patch(`${API_BASE}/${tableId}/columns/${columnKey}`, { label })
    return response.data
  },

  async deleteTable(tableId: string): Promise<void> {
    await axios.delete(`${API_BASE}/${tableId}`)
  },
}

export default api