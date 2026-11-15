import { useEffect, useRef, useState } from 'react'
import axios from 'axios'
import type { Background, PreparationProfile } from './CustomerPreparation'

export default function SalesMaterialPreview({ profile, background }: { profile: PreparationProfile; background: Background }) {
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => controller.current?.abort(), [])
  useEffect(() => () => { if (url) URL.revokeObjectURL(url) }, [url])
  async function generate() {
    if (busy) return
    const request = new AbortController()
    controller.current = request
    setBusy(true); setError('')
    try {
      const response = await axios.post('/api/v1/practice/preparation/material.pdf', { profile, background }, { responseType: 'blob', signal: request.signal, timeout: 30000 })
      if (!request.signal.aborted) setUrl(URL.createObjectURL(response.data))
    } catch (err) {
      if (!request.signal.aborted) {
        let message = 'PDF 生成失败，请稍后重试。'
        if (axios.isAxiosError(err) && err.response?.data instanceof Blob) {
          try { const data = JSON.parse(await err.response.data.text()); if (typeof data.detail === 'string') message = data.detail } catch { /* use safe fallback */ }
        }
        if (!request.signal.aborted) setError(message)
      }
    } finally { if (!request.signal.aborted) setBusy(false) }
  }
  return <div className="space-y-3 rounded-lg border bg-white p-4">
    <button type="button" disabled={busy} onClick={() => void generate()} className="block w-full rounded-lg bg-primary px-4 py-2 text-white disabled:opacity-40">{busy ? '生成中…' : '展示 PDF'}</button>
    {url ? <a href={url} download="销售准备资料.pdf" className="block rounded-lg border-2 border-primary bg-blue-50 px-4 py-2 text-center font-medium text-primary">下载 PDF</a> : <button type="button" disabled className="block w-full rounded-lg border-2 border-blue-200 px-4 py-2 text-sm text-gray-400">下载 PDF（请先展示 PDF）</button>}
    {busy && <p role="status" className="text-sm text-blue-600">正在生成相关资料...</p>}
    {error && <p role="alert" className="text-sm text-amber-700">{error}</p>}
    {url && <><h3 className="font-medium">销售资料预览</h3>
      <object data={url} type="application/pdf" aria-label="销售资料 PDF 预览" className="h-[650px] w-full rounded border"><p>当前浏览器无法内嵌预览，请使用下方按钮下载查看。</p></object>


      <p className="text-xs text-gray-500">可使用 PDF 查看器工具栏翻页和缩放。修改对象信息后需重新生成资料。</p></>}

  </div>
}
