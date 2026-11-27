import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import customerTableApi from '../../api/customerTables'
import type {
  CustomerColumn,
  CustomerRow,
  CustomerTableDetail,
  CustomerTableSummary,
  UncertainItem,
} from '../../api/customerTables'

const PAGE_SIZE = 50

const TYPE_LABELS: Record<string, string> = {
  phone: '电话', email: '邮箱', date: '日期', datetime: '时间',
  amount: '金额', number: '数值', percentage: '百分比', identifier: '编号',
  url: '网址', status: '状态', person: '联系人', company: '公司',
  address: '地址', note: '备注', text: '文本',
}

function formatDate(value: string) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function pendingItems(row: CustomerRow) {
  return (row.uncertain || []).filter(item => !item.reviewed)
}

interface EditableCellProps {
  value: string
  uncertain?: UncertainItem
  onSave: (value: string) => Promise<void>
}

function EditableCell({ value, uncertain, onSave }: EditableCellProps) {
  const [draft, setDraft] = useState(value)
  const [saving, setSaving] = useState(false)
  const original = useRef(value)

  useEffect(() => {
    setDraft(value)
    original.current = value
  }, [value])

  const commit = async () => {
    if (draft === original.current || saving) return
    setSaving(true)
    try {
      await onSave(draft)
      original.current = draft
    } finally {
      setSaving(false)
    }
  }

  return (
    <input
      value={draft}
      onChange={event => setDraft(event.target.value)}
      onBlur={() => { void commit() }}
      onKeyDown={event => {
        if (event.key === 'Enter') event.currentTarget.blur()
        if (event.key === 'Escape') {
          setDraft(original.current)
          event.currentTarget.blur()
        }
      }}
      title={uncertain ? `${uncertain.reason}\n原值：${uncertain.value}` : draft}
      aria-label={uncertain ? `待确认：${uncertain.reason}` : '可编辑单元格'}
      className={[
        'w-full min-w-[8rem] border-0 bg-transparent px-2 py-2 text-sm outline-none',
        'focus:bg-white focus:ring-2 focus:ring-inset focus:ring-primary/40',
        uncertain ? 'bg-amber-100 text-amber-950' : '',
        saving ? 'opacity-60' : '',
      ].join(' ')}
    />
  )
}

interface SelectionSquareProps {
  selected: boolean
  partial?: boolean
  label: string
  onClick: () => void
  disabled?: boolean
}

function SelectionSquare({ selected, partial = false, label, onClick, disabled = false }: SelectionSquareProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      aria-pressed={selected}
      title={label}
      className={[
        'flex h-10 w-10 items-center justify-center rounded-md border-2 transition',
        'bg-white/45 shadow-sm backdrop-blur-[1px]',
        selected
          ? 'border-red-600 bg-red-100 text-red-700 shadow-red-200'
          : 'border-red-400 text-transparent hover:border-red-600 hover:bg-red-50',
        disabled ? 'cursor-not-allowed opacity-40' : 'cursor-pointer',
      ].join(' ')}
    >
      {selected ? (
        <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
        </svg>
      ) : partial ? (
        <span className="h-0.5 w-5 rounded bg-red-500" />
      ) : null}
    </button>
  )
}

export default function CustomerManagementPage() {
  const navigate = useNavigate()
  const [tables, setTables] = useState<CustomerTableSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<CustomerTableDetail | null>(null)
  const [page, setPage] = useState(1)
  const [searchInput, setSearchInput] = useState('')
  const [appliedSearch, setAppliedSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [tableLoading, setTableLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [selectedRowIds, setSelectedRowIds] = useState<Set<string>>(new Set())
  const [bulkAction, setBulkAction] = useState<'confirm' | 'delete' | null>(null)
  const [isSelectionMode, setIsSelectionMode] = useState(false)

  const loadTableList = useCallback(async () => {
    const items = await customerTableApi.listTables()
    setTables(items)
    setSelectedId(current => {
      if (current && items.some(item => item.id === current)) return current
      return items[0]?.id || null
    })
    return items
  }, [])

  const loadSelectedTable = useCallback(async () => {
    if (!selectedId) {
      setDetail(null)
      return
    }
    setTableLoading(true)
    setError('')
    try {
      const data = await customerTableApi.getTable(selectedId, page, PAGE_SIZE, appliedSearch)
      setDetail(data)
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || requestError?.message || '加载客户表格失败')
      setDetail(null)
    } finally {
      setTableLoading(false)
    }
  }, [selectedId, page, appliedSearch])

  useEffect(() => {
    let active = true
    setLoading(true)
    loadTableList()
      .catch((requestError: any) => {
        if (active) setError(requestError?.response?.data?.detail || requestError?.message || '加载表格列表失败')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [loadTableList])

  useEffect(() => {
    void loadSelectedTable()
  }, [loadSelectedTable])

  useEffect(() => {
    setSelectedRowIds(new Set())
  }, [selectedId, page, appliedSearch])

  useEffect(() => {
    setSelectedRowIds(new Set())
    setIsSelectionMode(false)
  }, [selectedId, appliedSearch])

  const updateRowInState = (updated: CustomerRow) => {
    const previousRow = detail?.rows.find(row => row.id === updated.id)
    const pendingDelta = pendingItems(previousRow || updated).length - pendingItems(updated).length
    const nextUncertainCount = Math.max(0, (detail?.uncertain_count || 0) + pendingDelta)
    setDetail(current => current ? {
      ...current,
      rows: current.rows.map(row => row.id === updated.id ? updated : row),
      uncertain_count: Math.max(0, current.uncertain_count + pendingDelta),
    } : current)
    setTables(current => current.map(table => table.id === selectedId
      ? { ...table, uncertain_count: nextUncertainCount }
      : table))
  }
  const handleUpload = async (file?: File) => {
    if (!file || uploading) return
    setUploading(true)
    setError('')
    setNotice('AI 正在识别表头、数据类型和不确定内容，请稍候…')
    try {
      const imported = await customerTableApi.importTable(file)
      await loadTableList()
      setSelectedId(imported.id)
      setDetail(imported)
      setPage(1)
      setAppliedSearch('')
      setSearchInput('')
      setNotice(`已导入“${imported.name}”，共 ${imported.row_count} 条记录。`)
    } catch (requestError: any) {
      setNotice('')
      setError(requestError?.response?.data?.detail || requestError?.message || '上传或分析表格失败')
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleSaveCell = async (row: CustomerRow, columnKey: string, value: string) => {
    if (!selectedId) return
    try {
      const updated = await customerTableApi.updateRow(selectedId, row.id, { cells: { [columnKey]: value } })
      updateRowInState(updated)
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || requestError?.message || '保存单元格失败')
      throw requestError
    }
  }

  const confirmUncertain = async (row: CustomerRow, keys: string[], confirmAll = false) => {
    if (!selectedId) return
    try {
      const updated = await customerTableApi.updateRow(selectedId, row.id, {
        confirm_keys: keys,
        confirm_all: confirmAll,
      })
      updateRowInState(updated)
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || requestError?.message || '确认内容失败')
    }
  }

  const toggleRowSelection = (rowId: string) => {
    setSelectedRowIds(current => {
      const next = new Set(current)
      if (next.has(rowId)) next.delete(rowId)
      else next.add(rowId)
      return next
    })
  }

  const pageRows = detail?.rows || []
  const allPageSelected = pageRows.length > 0 && pageRows.every(row => selectedRowIds.has(row.id))
  const somePageSelected = pageRows.some(row => selectedRowIds.has(row.id)) && !allPageSelected


  const togglePageSelection = () => {
    setSelectedRowIds(current => {
      const next = new Set(current)
      if (allPageSelected) pageRows.forEach(row => next.delete(row.id))
      else pageRows.forEach(row => next.add(row.id))
      return next
    })
  }

  const beginBatchDelete = () => {
    if (!detail || detail.rows.length === 0 || bulkAction) return
    setSelectedRowIds(new Set())
    setIsSelectionMode(true)
    setNotice('请勾选要删除的客户记录，然后点击“删除选中”。')
  }

  const cancelBatchDelete = () => {
    setSelectedRowIds(new Set())
    setIsSelectionMode(false)
    setNotice('')
  }
  const handleConfirmAllUncertain = async () => {
    if (!selectedId || !detail || detail.uncertain_count === 0 || bulkAction) return
    if (!window.confirm(`确定确认整张表全部 ${detail.uncertain_count} 项黄色内容吗？原始数据不会删除。`)) return
    setBulkAction('confirm')
    setError('')
    try {
      const result = await customerTableApi.confirmAllUncertain(selectedId)
      setDetail(current => current ? {
        ...current,
        uncertain_count: result.remaining_count,
        rows: current.rows.map(row => ({
          ...row,
          uncertain: row.uncertain.map(item => ({ ...item, reviewed: true })),
        })),
      } : current)
      setTables(current => current.map(table => table.id === selectedId
        ? { ...table, uncertain_count: result.remaining_count }
        : table))
      setNotice(`已确认 ${result.confirmed_count} 项黄色内容。`)
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || requestError?.message || '批量确认失败')
    } finally {
      setBulkAction(null)
    }
  }

  const handleBatchDelete = async () => {
    if (!selectedId || selectedRowIds.size === 0 || bulkAction) return
    const rowIds = Array.from(selectedRowIds)
    if (!window.confirm(`确定删除当前页选中的 ${rowIds.length} 条客户记录吗？此操作不能撤销。`)) return
    setBulkAction('delete')
    setError('')
    try {
      const result = await customerTableApi.deleteRows(selectedId, rowIds)
      setSelectedRowIds(new Set())
      setIsSelectionMode(false)
      const targetPage = Math.min(page, Math.max(1, Math.ceil(result.remaining_rows / PAGE_SIZE)))
      if (targetPage !== page) setPage(targetPage)
      else await loadSelectedTable()
      await loadTableList()
      setNotice(`已删除 ${result.deleted_count} 条客户记录。`)
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || requestError?.message || '批量删除失败')
    } finally {
      setBulkAction(null)
    }
  }
  const handleDeleteRow = async (row: CustomerRow) => {
    if (!selectedId || !window.confirm(`确定删除第 ${row.position} 条客户记录吗？`)) return
    try {
      await customerTableApi.deleteRow(selectedId, row.id)
      setSelectedRowIds(current => {
        const next = new Set(current)
        next.delete(row.id)
        return next
      })
      await loadSelectedTable()
      await loadTableList()
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || requestError?.message || '删除客户记录失败')
    }
  }

  const handleAddRow = async () => {
    if (!selectedId) return
    try {
      await customerTableApi.addRow(selectedId)
      const targetPage = Math.max(1, Math.ceil(((detail?.total || 0) + 1) / PAGE_SIZE))
      const refreshed = await customerTableApi.getTable(selectedId, targetPage, PAGE_SIZE, '')
      setAppliedSearch('')
      setSearchInput('')
      setPage(targetPage)
      setDetail(refreshed)
      await loadTableList()
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || requestError?.message || '新增客户记录失败')
    }
  }

  const handleAddColumn = async () => {
    if (!selectedId) return
    const label = window.prompt('请输入新列名称')?.trim()
    if (!label) return
    try {
      const updated = await customerTableApi.addColumn(selectedId, label)
      setPage(1)
      setDetail(updated)
      await loadTableList()
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || requestError?.message || '新增列失败')
    }
  }
  const handleRenameColumn = async (column: CustomerColumn) => {
    if (!selectedId) return
    const label = window.prompt('修改列名', column.label)?.trim()
    if (!label || label === column.label) return
    try {
      await customerTableApi.renameColumn(selectedId, column.key, label)
      await loadSelectedTable()
      await loadTableList()
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || requestError?.message || '修改列名失败')
    }
  }

  const handleDeleteTable = async () => {
    if (!selectedId || !detail) return
    if (!window.confirm(`确定删除整张“${detail.name}”表格吗？此操作不能撤销。`)) return
    try {
      await customerTableApi.deleteTable(selectedId)
      setDetail(null)
      setSelectedId(null)
      await loadTableList()
      setNotice('客户表格已删除。')
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || requestError?.message || '删除表格失败')
    }
  }

  const handleSearch = (event: FormEvent) => {
    event.preventDefault()
    setPage(1)
    setAppliedSearch(searchInput.trim())
  }

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil((detail?.total || 0) / PAGE_SIZE)),
    [detail?.total],
  )

  const selectedSummary = tables.find(table => table.id === selectedId)

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-4 py-5 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">客户管理</h1>
            <p className="mt-1 text-sm text-gray-500">上传任意格式的客户表格，AI 自动识别列含义并生成可编辑网页表格。</p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <input
              ref={fileInputRef}
              type="file"
              accept=".xlsx,.xlsm,.csv"
              className="hidden"
              onChange={event => { void handleUpload(event.target.files?.[0]) }}
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="inline-flex items-center gap-2 rounded-xl bg-primary px-6 py-3 text-base font-semibold text-white shadow-md shadow-primary/20 transition hover:bg-primary/90 disabled:cursor-wait disabled:opacity-60"
            >
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 16V4m0 0L8 8m4-4l4 4M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3" />
              </svg>
              {uploading ? '正在分析表格…' : '上传表格'}
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-5 px-4 py-6">
        {notice && (
          <div className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800" role="status">
            {notice}
          </div>
        )}
        {error && (
          <div className="flex items-start justify-between gap-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
            <span>{error}</span>
            <button type="button" className="shrink-0 font-medium underline" onClick={() => setError('')}>关闭</button>
          </div>
        )}

        {loading ? (
          <div className="rounded-xl bg-white p-12 text-center text-gray-500 shadow-sm">正在加载客户表格…</div>
        ) : tables.length === 0 ? (
          <div className="rounded-xl border-2 border-dashed border-gray-300 bg-white px-6 py-16 text-center shadow-sm">
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-primary/10 text-primary">
              <svg className="h-8 w-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414A1 1 0 0119 9.414V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            <h2 className="mt-5 text-lg font-semibold text-gray-900">还没有客户表格</h2>
            <p className="mt-2 text-sm text-gray-500">点击右上角“上传表格”，支持 .xlsx、.xlsm 和 .csv。</p>
          </div>
        ) : (
          <>
            <section className="rounded-xl bg-white p-4 shadow-sm">
              <div className="mb-3 flex items-center justify-between gap-3">
                <p className="text-sm font-medium text-gray-700">已导入表格</p>
                {selectedSummary && (
                  <p className="text-xs text-gray-500">
                    {selectedSummary.source_filename || '手动表格'}
                    {selectedSummary.source_sheet ? ` · ${selectedSummary.source_sheet}` : ''}
                  </p>
                )}
              </div>
              <div className="flex gap-2 overflow-x-auto pb-1">
                {tables.map(table => (
                  <button
                    key={table.id}
                    type="button"
                    onClick={() => {
                      setSelectedId(table.id)
                      setPage(1)
                      setAppliedSearch('')
                      setSearchInput('')
                    }}
                    className={`min-w-[12rem] rounded-lg border px-4 py-3 text-left transition ${
                      table.id === selectedId
                        ? 'border-primary bg-primary/5 text-primary'
                        : 'border-gray-200 bg-gray-50 text-gray-700 hover:border-gray-300 hover:bg-white'
                    }`}
                  >
                    <span className="block truncate text-sm font-semibold">{table.name}</span>
                    <span className="mt-1 flex items-center gap-2 text-xs text-gray-500">
                      {table.row_count} 条记录
                      {table.uncertain_count > 0 && (
                        <span className="rounded-full bg-amber-100 px-2 py-0.5 font-medium text-amber-800">
                          待确认 {table.uncertain_count}
                        </span>
                      )}
                    </span>
                  </button>
                ))}
              </div>
            </section>

            {detail && (
              <section className="overflow-hidden rounded-xl bg-white shadow-sm">
                <div className="border-b border-gray-200 p-4">
                  <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="text-lg font-semibold text-gray-900">{detail.name}</h2>
                        {detail.uncertain_count > 0 ? (
                          <span className="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-900">
                            黄色待确认 {detail.uncertain_count} 项
                          </span>
                        ) : (
                          <span className="rounded-full bg-green-100 px-2.5 py-1 text-xs font-semibold text-green-800">
                            已全部检查
                          </span>
                        )}
                      </div>
                      <p className="mt-1 text-xs text-gray-500">
                        上次更新 {formatDate(detail.updated_at)} · 当前为动态列结构，不强制套用固定客户表头
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button type="button" onClick={() => { void handleAddRow() }} className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
                        新增记录
                      </button>
                      <button type="button" onClick={() => { void handleAddColumn() }} className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
                        新增列
                      </button>
                      <button
                        type="button"
                        onClick={() => { void handleConfirmAllUncertain() }}
                        disabled={detail.uncertain_count === 0 || bulkAction !== null}
                        className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-semibold text-amber-900 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-45"
                      >
                        {bulkAction === 'confirm' ? '正在确认…' : `批量确认黄色（${detail.uncertain_count}）`}
                      </button>
                      {!isSelectionMode ? (
                        <button
                          type="button"
                          onClick={beginBatchDelete}
                          disabled={detail.rows.length === 0 || bulkAction !== null}
                          className="rounded-lg border-2 border-red-400 bg-white px-4 py-2 text-sm font-semibold text-red-700 shadow-sm hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-45"
                        >
                          批量删除
                        </button>
                      ) : (
                        <>
                          <button
                            type="button"
                            onClick={() => { void handleBatchDelete() }}
                            disabled={selectedRowIds.size === 0 || bulkAction !== null}
                            className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-45"
                          >
                            {bulkAction === 'delete' ? '正在删除…' : `删除选中（${selectedRowIds.size}）`}
                          </button>
                          <button
                            type="button"
                            onClick={cancelBatchDelete}
                            disabled={bulkAction !== null}
                            className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-45"
                          >
                            取消
                          </button>
                        </>
                      )}
                      <button type="button" onClick={() => { void handleDeleteTable() }} className="rounded-lg border border-red-200 px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-50">
                        删除整张表
                      </button>
                    </div>
                  </div>

                  <form onSubmit={handleSearch} className="mt-4 flex flex-col gap-2 sm:flex-row">
                    <input
                      type="search"
                      value={searchInput}
                      onChange={event => setSearchInput(event.target.value)}
                      placeholder="搜索当前表格中的任意内容…"
                      className="min-w-0 flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                    />
                    <div className="flex gap-2">
                      <button type="submit" className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800">搜索</button>
                      {appliedSearch && (
                        <button
                          type="button"
                          onClick={() => { setSearchInput(''); setAppliedSearch(''); setPage(1) }}
                          className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
                        >
                          清除
                        </button>
                      )}
                    </div>
                  </form>

                  {isSelectionMode && (
                    <div className="mt-4 flex flex-col gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 sm:flex-row sm:items-center sm:justify-between">
                      <span>批量删除模式：请勾选客户记录。当前已选 {selectedRowIds.size} 条。</span>
                      <button type="button" onClick={cancelBatchDelete} className="self-start font-semibold text-red-700 underline sm:self-auto">
                        退出批量删除
                      </button>
                    </div>
                  )}
                </div>

                <div className={`relative overflow-x-auto ${tableLoading ? 'opacity-60' : ''}`}>
                  {tableLoading && (
                    <div className="absolute inset-0 z-20 flex items-center justify-center bg-white/40">
                      <span className="rounded-full bg-white px-4 py-2 text-sm text-gray-600 shadow">正在加载…</span>
                    </div>
                  )}
                  <table className="min-w-full border-collapse text-left">
                    <thead className="sticky top-0 z-10 bg-gray-100">
                      <tr>
                        {isSelectionMode && (
                          <th className="sticky left-0 z-20 w-16 border-b border-r border-red-200 bg-red-50/80 px-2 py-3 text-center">
                            <SelectionSquare
                              selected={allPageSelected}
                              partial={somePageSelected}
                              label={allPageSelected ? '取消选择当前页全部记录' : '选择当前页全部记录'}
                              onClick={togglePageSelection}
                            />
                          </th>
                        )}
                        <th className={`sticky ${isSelectionMode ? 'left-16' : 'left-0'} z-20 w-14 border-b border-r border-gray-200 bg-gray-100 px-2 py-3 text-center text-xs font-semibold text-gray-500`}>#</th>
                        <th className={`sticky ${isSelectionMode ? 'left-[7.5rem]' : 'left-14'} z-20 min-w-[5.5rem] border-b border-r border-gray-200 bg-gray-100 px-2 py-3 text-center text-xs font-semibold text-gray-500`}>回访</th>
                        {detail.columns.map(column => (
                          <th key={column.key} className="min-w-[9rem] border-b border-r border-gray-200 px-3 py-2 align-top">
                            <button
                              type="button"
                              onClick={() => { void handleRenameColumn(column) }}
                              className="block max-w-[16rem] truncate text-left text-sm font-semibold text-gray-800 hover:text-primary"
                              title="点击修改列名"
                            >
                              {column.label}
                            </button>
                            <div className="mt-1 text-[11px] font-normal text-gray-500">
                              {TYPE_LABELS[column.semantic_type] || column.semantic_type}
                              {column.confidence < 0.65 ? ' · 低置信度' : ''}
                            </div>
                          </th>
                        ))}
                        <th aria-label="无表头待确认内容" title="无表头待确认内容" className="min-w-[18rem] border-b border-r border-amber-300 bg-amber-100 px-3 py-2" />
                        <th className="min-w-[6rem] border-b border-gray-200 px-3 py-2 text-center text-xs font-semibold text-gray-500">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detail.rows.length === 0 ? (
                        <tr>
                          <td colSpan={detail.columns.length + 4 + (isSelectionMode ? 1 : 0)} className="px-4 py-12 text-center text-sm text-gray-500">
                            {appliedSearch ? '没有匹配的客户记录。' : '这张表格暂时没有客户记录。'}
                          </td>
                        </tr>
                      ) : detail.rows.map(row => {
                        const unresolved = pendingItems(row)
                        const selected = selectedRowIds.has(row.id)
                        return (
                          <tr key={row.id} className={`border-b border-gray-100 ${selected ? 'bg-red-50/70' : 'hover:bg-gray-50/60'}`}>
                            {isSelectionMode && (
                              <td className={`sticky left-0 z-10 border-r border-red-200 px-2 py-2 text-center ${selected ? 'bg-red-50' : 'bg-white/80'}`}>
                                <SelectionSquare
                                  selected={selected}
                                  label={selected ? `取消选择第 ${row.position} 条记录` : `选择第 ${row.position} 条记录`}
                                  onClick={() => toggleRowSelection(row.id)}
                                />
                              </td>
                            )}
                            <td className={`sticky ${isSelectionMode ? 'left-16' : 'left-0'} z-10 border-r border-gray-200 px-2 py-2 text-center text-xs text-gray-500 ${selected ? 'bg-red-50' : 'bg-white'}`}>
                              {row.position}
                            </td>
                            <td className={`sticky ${isSelectionMode ? 'left-[7.5rem]' : 'left-14'} z-10 border-r border-gray-200 px-2 py-2 text-center ${selected ? 'bg-red-50' : 'bg-white'}`}>
                              <button
                                type="button"
                                onClick={() => navigate('/practice', { state: { customerContext: { training_mode: 'follow_up', industry: '', scale: '', pain_points: [] }, userContext: { follow_up_source: { tableId: detail.id, rowId: row.id } } } })}
                                className="rounded-md bg-primary px-2.5 py-1.5 text-xs font-medium text-white hover:bg-blue-700"
                              >
                                回访
                              </button>
                            </td>
                            {detail.columns.map(column => {
                              const uncertain = unresolved.find(item => item.column_key === column.key)
                              return (
                                <td key={column.key} className="border-r border-gray-100 p-0 align-top">
                                  <EditableCell
                                    value={row.cells[column.key] || ''}
                                    uncertain={uncertain}
                                    onSave={value => handleSaveCell(row, column.key, value)}
                                  />
                                </td>
                              )
                            })}
                            <td className={`border-r border-amber-200 p-2 align-top ${unresolved.length > 0 ? 'bg-amber-50' : ''}`}>
                              {unresolved.length === 0 ? (
                                <span className="block min-h-[2.25rem]" />
                              ) : (
                                <div className="space-y-2">
                                  {unresolved.map(item => (
                                    <div key={item.column_key} className="rounded-md border border-amber-200 bg-amber-100/80 p-2 text-xs text-amber-950">
                                      <div className="mb-1 flex items-center justify-between gap-2">
                                        <span className="font-semibold">{item.label}</span>
                                        <button
                                          type="button"
                                          onClick={() => { void confirmUncertain(row, [item.column_key]) }}
                                          className="shrink-0 rounded bg-white px-2 py-0.5 font-medium text-amber-900 shadow-sm hover:bg-amber-50"
                                        >
                                          确认
                                        </button>
                                      </div>
                                      <p className="break-words font-medium">{item.value}</p>
                                      <p className="mt-1 text-[11px] text-amber-800">{item.reason}</p>
                                    </div>
                                  ))}
                                  {unresolved.length > 1 && (
                                    <button
                                      type="button"
                                      onClick={() => { void confirmUncertain(row, [], true) }}
                                      className="w-full rounded border border-amber-300 bg-white px-2 py-1 text-xs font-medium text-amber-900 hover:bg-amber-50"
                                    >
                                      确认本行全部内容
                                    </button>
                                  )}
                                </div>
                              )}
                            </td>
                            <td className="px-2 py-2 text-center align-top">
                              <button
                                type="button"
                                onClick={() => { void handleDeleteRow(row) }}
                                className="rounded px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50"
                              >
                                删除
                              </button>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>

                <div className="flex flex-col gap-3 border-t border-gray-200 px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between">
                  <p className="text-gray-500">
                    {detail.total === 0
                      ? '0 条记录'
                      : `第 ${(detail.page - 1) * detail.page_size + 1}-${Math.min(detail.page * detail.page_size, detail.total)} 条，共 ${detail.total} 条`}
                  </p>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      disabled={page <= 1}
                      onClick={() => setPage(current => Math.max(1, current - 1))}
                      className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-700 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      上一页
                    </button>
                    <span className="min-w-[4rem] text-center text-gray-500">{page} / {totalPages}</span>
                    <button
                      type="button"
                      disabled={page >= totalPages}
                      onClick={() => setPage(current => Math.min(totalPages, current + 1))}
                      className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-700 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      下一页
                    </button>
                  </div>
                </div>
              </section>
            )}
          </>
        )}
      </main>
    </div>
  )
}
