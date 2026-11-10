import { useEffect, useState } from 'react'
import { api } from './api'
type Doc = { id: number; filename: string; size: number }
type Score = { score: number; breakdown: { item: string; status: string }[] }
export default function Evidence({ id }: { id: number }) {
  const [docs, setDocs] = useState<Doc[]>([]), [score, setScore] = useState<Score | null>(null)
  const [file, setFile] = useState<File | null>(null), [busy, setBusy] = useState(false)
  const [error, setError] = useState(''), [notice, setNotice] = useState('')
  async function load() {
    const [d, s] = await Promise.all([api<{ items: Doc[] }>(`/api/transactions/${id}/evidence`), api<Score | null>(`/api/transactions/${id}/readiness`)])
    setDocs(d.items); setScore(s)
  }
  useEffect(() => { void load().catch(e => setError(e.message)) }, [id])
  async function action(fn: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('')
    try { await fn() } catch (e) { setError(e instanceof Error ? e.message : 'Request failed.') }
    finally { setBusy(false) }
  }
  return <section className="mt-6 border-t pt-4" aria-label="Evidence vault">
    <h3 className="font-semibold">Evidence vault</h3>
    <p className="my-2 text-sm">Text-based PDFs, up to 10 MB and 50 pages each.</p>
    <input aria-label="Evidence PDF" type="file" accept="application/pdf,.pdf" onChange={e => setFile(e.target.files?.[0] || null)} />
    <button disabled={busy || !file} onClick={() => void action(async () => {
      if (!file) return
      const form = new FormData(); form.append('file', file)
      await api(`/api/transactions/${id}/evidence`, { method: 'POST', body: form }); await load(); setNotice('Evidence saved.')
    })}>Upload PDF</button>
    <ul className="my-3">{docs.map(d => <li key={d.id}>{d.filename} · {Math.ceil(d.size / 1024)} KB</li>)}</ul>
    <p className="text-sm">Analyze sends document text to Google Gemini. Only exact source quotations are retained. Coverage is a checklist, not a prediction of winning a dispute.</p>
    <button className="my-3" disabled={busy || !docs.length} onClick={() => void action(async () => {
      const r = await api<{ readiness: Score }>(`/api/transactions/${id}/analyze`, { method: 'POST' }); setScore(r.readiness); setNotice('Analysis complete.')
    })}>{busy ? 'Working…' : 'Analyze with Gemini'}</button>
    {score && <div><p className="font-semibold">Evidence coverage: {score.score}/100</p><ul>{score.breakdown.map(b => <li key={b.item}>{b.item.replaceAll('_', ' ')}: {b.status}</li>)}</ul></div>}
    <button className="ml-3" disabled={busy} onClick={() => void action(async () => {
      const r = await api<{ source: string; items: unknown[] }>('/api/disputes/sync', { method: 'POST', body: JSON.stringify({ transaction_id: id }) })
      setNotice(r.source === 'fixture' ? 'Simulated dispute ready. Open Disputes below.' : `${r.items.length} matching dispute(s) synchronized from the first PayPal page.`)
      window.dispatchEvent(new Event('disputes-updated'))
    })}>Load dispute for this transaction</button>
    {notice && <p role="status" className="mt-3">{notice}</p>}
    {error && <p role="alert" className="mt-3 text-red-700">{error}</p>}
  </section>
}
