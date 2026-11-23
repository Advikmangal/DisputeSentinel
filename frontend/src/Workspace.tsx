import { useCallback, useEffect, useState } from 'react'
import { api, downloadFile } from './api'
import type { Transaction } from './api'

type Readiness = { score: number; note: string; missing_items: string[]; breakdown: { key: string; label: string; status: string; points: number; weight: number }[] }
type Doc = { id: number; filename: string; size: number; pages: number }
type Fact = { document_id: number; page: number; excerpt: string; fact_type: string }
type DisputeResponse = { draft_text: string; status: string; citations: Fact[] }
type Dispute = { id: number; transaction_id: number; reason: string; status: string; is_fixture: boolean; response_due_at: string | null; response: DisputeResponse | null }
const errorText = (e: unknown) => e instanceof Error ? e.message : 'Request failed.'
export function ErrorMessage({ message }: { message: string }) { return message ? <p role="alert" className="error-box">{message}</p> : null }

export function Dashboard({ navigate }: { navigate: (page: string) => void }) {
  const [data, setData] = useState<{ transactions: number; verified: number; verified_totals: Record<string, string>; open_disputes: number; simulated_disputes: number; readiness: (Readiness & { transaction_id: number; description: string })[] } | null>(null)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState('all')
  const load = useCallback(() => { setError(''); void api<typeof data>('/api/dashboard/summary').then(setData).catch(e => setError(errorText(e))) }, [])
  useEffect(load, [load])
  return <main className="page"><div className="page-heading"><div><p className="eyebrow">MERCHANT WORKSPACE</p><h2>Evidence before escalation.</h2><p>Track payments, close evidence gaps, and prepare a response you can stand behind.</p></div><button onClick={load}>Refresh</button></div>
    <ErrorMessage message={error} />
    {!data ? <p role="status">{error ? 'Dashboard unavailable.' : 'Loading your workspace…'}</p> : <>
      <div className="metrics">{[['Transactions', data.transactions], ['Verified payments', data.verified], ['Open disputes', data.open_disputes], ['Simulated disputes', data.simulated_disputes]].map(([label, value]) => <section className="card" key={label}><p>{label}</p><strong className="metric-value">{value}</strong></section>)}</div>
      <section className="card"><div className="section-heading"><h3>Evidence coverage</h3><select aria-label="Filter readiness" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">All transactions</option><option value="gaps">Needs evidence</option><option value="ready">80% or more</option></select></div><p className="muted">A checklist score, not a prediction of winning a dispute.</p>
        {!data.readiness.length ? <div className="empty"><h3>Your first payment starts the story.</h3><p>Create a Sandbox payment, then attach delivery records and buyer communications.</p><button className="primary" onClick={() => navigate('Payments')}>Create a payment</button></div> : data.readiness.filter(r => filter === 'all' || (filter === 'gaps' ? r.score < 80 : r.score >= 80)).map(r => <div className="coverage-row" key={r.transaction_id}><div><strong>#{r.transaction_id} · {r.description || 'Digital service'}</strong><p className="muted">{r.missing_items.join(' · ') || 'All checklist categories covered'}</p></div><progress max={100} value={r.score} /><b>{r.score}%</b></div>)}
      </section><div className="two-columns"><section className="card"><h3>Verified Sandbox volume</h3>{Object.entries(data.verified_totals).length ? Object.entries(data.verified_totals).map(([currency, amount]) => <p className="metric-value" key={currency}>{amount} <small>{currency}</small></p>) : <p className="muted">No verified payments yet.</p>}</section><section className="card"><h3>Next step: strengthen your evidence</h3><p className="muted">Upload a text PDF, run AI extraction, and review every cited quotation.</p><button onClick={() => navigate('Evidence Vault')}>Open Evidence Vault →</button></section></div>
    </>}
  </main>
}

export function EvidenceVault() {
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [selected, setSelected] = useState('')
  const [error, setError] = useState('')
  useEffect(() => { void api<{ items: Transaction[] }>('/api/transactions').then(d => { setTransactions(d.items); setSelected(String(d.items[0]?.id || '')) }).catch(e => setError(errorText(e))) }, [])
  return <main className="page"><div className="page-heading"><div><p className="eyebrow">PRIVATE DOCUMENTS</p><h2>Evidence Vault</h2><p>Keep the original document next to every extracted fact.</p></div></div><ErrorMessage message={error} />
    <label className="card">Transaction<select value={selected} onChange={e => setSelected(e.target.value)}><option value="">Select a transaction</option>{transactions.map(t => <option key={t.id} value={t.id}>#{t.id} · {t.description || 'Digital service'} · {t.amount} {t.currency}{t.is_demo ? ' · Simulated' : ''}</option>)}</select></label>
    {selected ? <EvidenceDetail key={selected} tid={Number(selected)} /> : <p className="empty">Create a payment in Payments to start collecting evidence.</p>}
  </main>
}

function EvidenceDetail({ tid }: { tid: number }) {
  const [docs, setDocs] = useState<Doc[]>([])
  const [facts, setFacts] = useState<Fact[]>([])
  const [score, setScore] = useState<Readiness | null>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const load = useCallback(async () => {
    const [e, r] = await Promise.all([api<{ items: Doc[]; facts: Fact[] }>(`/api/transactions/${tid}/evidence`), api<Readiness>(`/api/transactions/${tid}/readiness`)])
    setDocs(e.items); setFacts(e.facts); setScore(r)
  }, [tid])
  useEffect(() => { void load().catch(e => setError(errorText(e))) }, [load])
  async function action(label: string, fn: () => Promise<unknown>) {
    setBusy(label); setError('')
    try { await fn(); await load() } catch (e) { setError(errorText(e)) } finally { setBusy('') }
  }
  return <><ErrorMessage message={error} /><div className="two-columns"><section className="card"><h3>Add delivery evidence</h3><p className="muted">Text PDFs only · up to 10 MB and 50 pages · 10 documents per transaction. Documents remain private to your account.</p><input aria-label="Evidence PDF" type="file" accept="application/pdf,.pdf" disabled={!!busy} onChange={e => setFile(e.target.files?.[0] || null)} /><div className="actions"><button disabled={!file || !!busy} onClick={() => void action('Uploading…', async () => { if (!file) return; if (file.size > 10_000_000) throw new Error('PDF must be at most 10 MB.'); await api(`/api/transactions/${tid}/evidence?filename=${encodeURIComponent(file.name)}`, { method: 'POST', headers: { 'Content-Type': 'application/pdf' }, body: file }); setFile(null) })}>Upload PDF</button><button className="primary" disabled={!docs.length || !!busy} onClick={() => void action('Analyzing documents. This can take several minutes…', () => api(`/api/transactions/${tid}/analyze`, { method: 'POST' }))}>Analyze evidence</button></div><p className="muted">Analysis sends extracted document text to Gemini. Review the resulting categories and quotations before use.</p>{busy && <p role="status">{busy}</p>}</section>
      <section className="card"><h3>Readiness checklist</h3>{score && <><p className="metric-value">{score.score}<small> / 100</small></p>{score.breakdown.map(b => <div className="checklist-row" key={b.key}><span>{b.label}</span><span className={`badge ${b.status === 'present' ? 'success' : ''}`}>{b.status} · {b.points}/{b.weight}</span></div>)}<p className="muted">{score.note}</p></>}</section></div>
    <section className="card"><h3>Source documents</h3>{!docs.length ? <p className="muted">No documents yet.</p> : docs.map(d => <div className="checklist-row" key={d.id}><div><strong>{d.filename}</strong><p className="muted">{d.pages} pages · {(d.size / 1024).toFixed(1)} KB</p></div><button onClick={() => void downloadFile(`/api/evidence/${d.id}/download`, d.filename).catch(e => setError(errorText(e)))}>Download</button></div>)}</section>
    <section className="card"><h3>Source-checked quotations</h3><p className="muted">The excerpt must exist on the cited page. This check does not establish that the document is authentic.</p>{!facts.length ? <p>No extracted facts yet. Upload and analyze a document.</p> : facts.map((f, i) => <blockquote key={i}><span className="badge">{f.fact_type.replaceAll('_', ' ')}</span><p>“{f.excerpt}”</p><button className="text-button" onClick={() => void downloadFile(`/api/evidence/${f.document_id}/download`, `source-${f.document_id}.pdf`).catch(e => setError(errorText(e)))}>Document #{f.document_id} · page {f.page} ↗</button></blockquote>)}</section>
  </>
}

export function Disputes() {
  const [items, setItems] = useState<Dispute[]>([])
  const [selected, setSelected] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const load = useCallback(async () => { const d = await api<{ items: Dispute[] }>('/api/disputes'); setItems(d.items) }, [])
  useEffect(() => { void load().catch(e => setError(errorText(e))) }, [load])
  const current = items.find(i => i.id === selected)
  return <main className="page"><div className="page-heading"><div><p className="eyebrow">REVIEW BEFORE EXPORT</p><h2>Dispute Agent</h2><p>Prepare cited responses, review the wording, then approve an export.</p></div><button className="primary" disabled={busy} onClick={async () => { setBusy(true); setError(''); try { await api('/api/disputes/sync', { method: 'POST' }); await load() } catch (e) { setError(errorText(e)) } finally { setBusy(false) } }}>{busy ? 'Syncing…' : 'Sync disputes'}</button></div>
    <p className="notice">Simulated disputes are labeled. Exporting a response does not submit it to PayPal.</p><ErrorMessage message={error} />
    {!items.length ? <section className="card empty"><h3>No disputes to review</h3><p>Create a payment, then sync. In fixture mode this creates a clearly labeled simulated case.</p></section> : <div className="dispute-layout"><section className="card">{items.map(d => <button className={`dispute-item ${selected === d.id ? 'selected' : ''}`} key={d.id} onClick={() => setSelected(d.id)}><strong>Case #{d.id} · Transaction #{d.transaction_id}</strong><span>{d.reason.replaceAll('_', ' ')}</span><span className="badge">{d.is_fixture ? 'Simulated' : 'PayPal Sandbox'}</span>{d.response_due_at && <small>Response due {new Date(d.response_due_at).toLocaleDateString()}</small>}</button>)}</section>{current ? <DisputeEditor key={`${current.id}-${current.response?.status}-${current.response?.draft_text}`} dispute={current} reload={load} /> : <section className="card empty">Select a case to review its evidence.</section>}</div>}
  </main>
}

function DisputeEditor({ dispute: d, reload }: { dispute: Dispute; reload: () => Promise<void> }) {
  const [text, setText] = useState(d.response?.draft_text || '')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const dirty = text !== (d.response?.draft_text || '')
  async function action(fn: () => Promise<unknown>) { setBusy(true); setError(''); try { await fn(); await reload() } catch (e) { setError(errorText(e)) } finally { setBusy(false) } }
  return <section className="card"><div className="section-heading"><h3>Response #{d.id}</h3><span className="badge">{d.response?.status || 'No draft'}</span></div><ErrorMessage message={error} />
    <button disabled={busy} onClick={() => void action(() => api(`/api/disputes/${d.id}/draft`, { method: 'POST' }))}>{d.response ? 'Generate a new draft' : 'Generate cited draft'}</button>
    {d.response && <><label className="editor-label">Review and edit<textarea rows={14} value={text} onChange={e => setText(e.target.value)} disabled={busy} /></label><p className="muted">Edits require fresh approval. Added claims are your responsibility; compare them with the source quotations below.</p><div className="actions"><button disabled={busy || !dirty || !text.trim()} onClick={() => void action(() => api(`/api/disputes/${d.id}/response`, { method: 'PUT', body: JSON.stringify({ draft_text: text }) }))}>Save changes</button><button className="primary" disabled={busy || dirty || d.response.status !== 'draft'} onClick={() => void action(() => api(`/api/disputes/${d.id}/approve`, { method: 'POST' }))}>Approve response</button><button disabled={busy || dirty || !['approved', 'exported'].includes(d.response.status)} onClick={() => void action(() => downloadFile(`/api/disputes/${d.id}/export`, `dispute-${d.id}.md`))}>Export Markdown</button></div>
    <h4 className="editor-label">Source quotations</h4>{d.response.citations.map((c, i) => <blockquote key={i}><p>“{c.excerpt}”</p><button className="text-button" onClick={() => void downloadFile(`/api/evidence/${c.document_id}/download`, `source-${c.document_id}.pdf`).catch(e => setError(errorText(e)))}>Document #{c.document_id} · page {c.page} ↗</button></blockquote>)}</>}
  </section>
}
