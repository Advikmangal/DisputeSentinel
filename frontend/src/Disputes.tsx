import { useEffect, useState } from 'react'
import { api } from './api'
type Citation = { document_id: number; page: number; excerpt: string }
type Draft = { draft_text: string; citations: Citation[]; status: string }
type Dispute = { id: number; transaction_id: number; reason: string; is_fixture: boolean; response: Draft | null }
export default function Disputes() {
  const [items, setItems] = useState<Dispute[]>([]), [selected, setSelected] = useState<Dispute | null>(null)
  const [text, setText] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState(''), [exported, setExported] = useState('')
  async function load() { setItems((await api<{ items: Dispute[] }>('/api/disputes')).items) }
  useEffect(() => {
    const refresh = () => { void load().catch(e => setError(e.message)) }
    refresh(); window.addEventListener('disputes-updated', refresh)
    return () => window.removeEventListener('disputes-updated', refresh)
  }, [])
  async function act(id: number, operation: string, options: RequestInit = { method: 'POST' }) {
    setBusy(true); setError(''); setExported('')
    try {
      const r = await api<{ response: Draft; dispute: Dispute; delivery?: { content: string } }>(`/api/disputes/${id}/${operation}`, options)
      setSelected({ ...r.dispute, response: r.response }); setText(r.response.draft_text)
      if (r.delivery) setExported(r.delivery.content)
      await load()
    } catch (e) { setError(e instanceof Error ? e.message : 'Request failed.') }
    finally { setBusy(false) }
  }
  return <section className="rounded border bg-white p-4" aria-label="Disputes">
    <h3 className="font-semibold">Disputes</h3>
    <p className="my-2 text-sm">Open a transaction to upload evidence and load its dispute. Review and approve responses before exporting. Exports are not sent to PayPal.</p>
    {!items.length && <p>No disputes loaded yet.</p>}
    {items.map(d => <div key={d.id} className="my-3 flex flex-wrap items-center gap-3 border-t pt-3"><span>#{d.id} · Transaction {d.transaction_id} · {d.reason.replaceAll('_', ' ')}</span>{d.is_fixture && <strong className="text-amber-800">Simulated</strong>}<button disabled={busy} onClick={() => void act(d.id, 'draft')}>{d.response ? 'Review response' : 'Draft from evidence'}</button></div>)}
    {selected?.response && <div className="mt-4 space-y-3">
      <h4 className="font-semibold">{selected.is_fixture ? 'Simulated ' : ''}Response #{selected.id} · {selected.response.status}</h4>
      <label>Response text<textarea className="block min-h-48 w-full rounded border p-3" value={text} disabled={busy || selected.response.status === 'exported'} onChange={e => setText(e.target.value)} /></label>
      <p className="text-sm">Quotations are document claims. Review accuracy and relevance; wording you add remains your responsibility.</p>
      <ul>{selected.response.citations.map((c, i) => <li key={i}>[{i+1}] Document {c.document_id}, page {c.page}: {c.excerpt}</li>)}</ul>
      {selected.response.status !== 'exported' && <>
        <button disabled={busy || text === selected.response.draft_text} onClick={() => void act(selected.id, 'response', { method: 'PUT', body: JSON.stringify({ draft_text: text, citations: selected.response!.citations }) })}>Save edits</button>
        <button className="ml-2" disabled={busy || text !== selected.response.draft_text || selected.response.status === 'approved'} onClick={() => void act(selected.id, 'approve')}>Approve reviewed response</button>
      </>}
      <button className="ml-2" disabled={busy || text !== selected.response.draft_text || !['approved', 'exported'].includes(selected.response.status)} onClick={() => void act(selected.id, 'submit')}>Export response</button>
      {exported && <><p role="status">Export ready. Nothing was sent to PayPal.</p><pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-3">{exported}</pre><a download={`dispute-${selected.id}.md`} href={`data:text/markdown;charset=utf-8,${encodeURIComponent(exported)}`} className="underline">Download Markdown</a></>}
    </div>}
    {error && <p role="alert" className="mt-3 text-red-700">{error}</p>}
  </section>
}
