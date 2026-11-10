import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { api, getToken } from './api'
import type { Transaction } from './api'
import { loadPayPal } from './paypal'
import Evidence from './Evidence'
import Disputes from './Disputes'
const message = (e: unknown) => e instanceof Error ? e.message : 'Something went wrong.'
type Checkout = { amount: string; description: string; key: string }
function CheckoutButton({ checkout, onVerified }: { checkout: Checkout; onVerified: () => void }) {
  const container = useRef<HTMLDivElement>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('Loading PayPal…')
  const [retryOrder, setRetryOrder] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [verified, setVerified] = useState(false)
  const active = useRef(true)
  const session = useRef(getToken())
  const finish = useCallback(async (orderID: string) => {
    if (!active.current || getToken() !== session.current) return
    setBusy(true); setError(''); setNotice('Verifying payment…')
    try {
      const tx = await api<Transaction>('/api/payments/capture', { method: 'POST', body: JSON.stringify({ order_id: orderID }) })
      if (tx.status !== 'VERIFIED') throw new Error('The backend has not verified this payment.')
      if (!active.current) return
      setRetryOrder(null); setVerified(true); setNotice('Payment VERIFIED.'); onVerified()
      return true
    } catch (e) {
      if (!active.current) return
      setNotice(''); setError(`Capture failed: ${message(e)} No verified payment has been confirmed. Retry verification for the same order.`); setRetryOrder(orderID)
    } finally { if (active.current) setBusy(false) }
  }, [onVerified])
  useEffect(() => {
    let cancelled = false
    active.current = true
    let buttons: ReturnType<Awaited<ReturnType<typeof loadPayPal>>['Buttons']> | undefined
    loadPayPal().then(async paypal => {
      if (cancelled || !container.current) return
      buttons = paypal.Buttons({
        style: { label: 'pay' },
        createOrder: async () => {
          if (cancelled || session.current !== getToken()) throw new Error('Please sign in again.')
          setError(''); setNotice('Creating Sandbox order…')
          try {
            const order = await api<{ transaction: Transaction }>('/api/payments/create-order', {
              method: 'POST', headers: { 'Idempotency-Key': checkout.key },
              body: JSON.stringify({ amount: checkout.amount, currency: 'USD', description: checkout.description }),
            })
            if (cancelled) throw new Error('Checkout closed.')
            setNotice('Approve the payment in the PayPal Sandbox window.')
            return order.transaction.paypal_order_id
          } catch (e) { if (!cancelled) { setError(message(e)); setNotice('') }; throw e }
        },
        onApprove: async data => {
          if (!await finish(data.orderID)) throw new Error('Backend capture was not verified.')
        },
        onCancel: () => { if (!cancelled) setNotice('Checkout canceled. No verified payment was confirmed.') },
        onError: () => { if (!cancelled) { setError(previous => previous || 'PayPal checkout failed. Retry or check the transaction list.'); setNotice('') } },
      })
      await buttons.render(container.current)
      if (!cancelled) setNotice('Pay with PayPal using a Sandbox buyer account.')
    }).catch(e => { if (!cancelled) { setError(message(e)); setNotice('') } })
    return () => { cancelled = true; active.current = false; void buttons?.close().catch(() => {}) }
  }, [checkout, finish])
  return <section className="my-4 space-y-3" aria-label="Pay with PayPal">
    <div ref={container} className={busy || retryOrder || verified ? 'hidden' : 'max-w-sm'} />
    {notice && <p role="status">{notice}</p>}
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {retryOrder && <button disabled={busy} onClick={() => void finish(retryOrder)}>Retry verification</button>}
  </section>
}
export default function Payments() {
  const [items, setItems] = useState<Transaction[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [detail, setDetail] = useState<Transaction | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [recovering, setRecovering] = useState<number | null>(null)
  const [checkout, setCheckout] = useState<Checkout | null>(null)
  const [amount, setAmount] = useState('1.00')
  const [description, setDescription] = useState('')
  const detailRequest = useRef(0)
  const refresh = useCallback(() => {
    setLoading(true); setError('')
    void api<{ items: Transaction[] }>('/api/transactions').then(data => setItems(data.items))
      .catch(e => setError(message(e))).finally(() => setLoading(false))
  }, [])
  useEffect(refresh, [refresh])
  function prepare(event: FormEvent) {
    event.preventDefault()
    setCheckout({ amount: Number(amount).toFixed(2), description, key: crypto.randomUUID() })
  }
  async function recover(tx: Transaction) {
    setRecovering(tx.id); setError('')
    try {
      const updated = await api<Transaction>('/api/payments/capture', { method: 'POST', body: JSON.stringify({ order_id: tx.paypal_order_id }) })
      setDetail(updated); refresh()
    } catch (e) { setError(message(e)) }
    finally { setRecovering(null) }
  }
  async function openDetail(id: number) {
    const request = ++detailRequest.current
    setDetailLoading(true); setDetail(null); setError('')
    try { const data = await api<Transaction>(`/api/transactions/${id}`); if (request === detailRequest.current) setDetail(data) }
    catch (e) { if (request === detailRequest.current) setError(message(e)) }
    finally { if (request === detailRequest.current) setDetailLoading(false) }
  }
  return <main className="mx-auto max-w-5xl space-y-6 p-6">
    <h2 className="text-2xl font-semibold">Payments</h2>
    <section className="rounded border bg-white p-4"><h3 className="mb-3 font-semibold">New Sandbox payment</h3>
      {!checkout ? <form onSubmit={prepare} className="flex flex-wrap items-end gap-4">
        <label>Amount (USD)<input type="number" step="0.01" min="0.01" max="9999999" required value={amount} onChange={e => setAmount(e.target.value)} /></label>
        <label>Description<input maxLength={1000} value={description} onChange={e => setDescription(e.target.value)} /></label><button type="submit">Continue to PayPal</button>
      </form> : <><p>{checkout.amount} USD — {checkout.description || 'Digital service'}</p><CheckoutButton key={checkout.key} checkout={checkout} onVerified={refresh} /><button onClick={() => setCheckout(null)}>New payment</button></>}
    </section>
    <section className="rounded border bg-white p-4"><div className="mb-4 flex items-center justify-between"><h3 className="font-semibold">Transactions</h3><button onClick={refresh} disabled={loading}>Refresh</button></div>
      {error && <p role="alert" className="mb-3 text-red-700">{error}</p>}
      {loading ? <p role="status">Loading transactions…</p> : !items.length ? <p>{error ? 'Transactions could not be loaded.' : 'No transactions yet. Create your first Sandbox payment above.'}</p> :
        <div className="overflow-x-auto"><table className="w-full text-left"><thead><tr><th>Status</th><th>Amount</th><th>Payer email</th><th>Date</th><th>Details</th></tr></thead><tbody>{items.map(tx => <tr key={tx.id} className="border-t"><td><span className={tx.status === 'VERIFIED' ? 'rounded bg-green-100 px-2 py-1 text-green-800' : ''}>{tx.status}</span>{tx.is_demo && <span className="ml-2 text-amber-800">Demo — Simulated</span>}</td><td>{tx.amount} {tx.currency}</td><td>{tx.payer_email || '—'}</td><td>{new Date(tx.captured_at || tx.created_at).toLocaleString()}</td><td><button onClick={() => void openDetail(tx.id)}>View #{tx.id}</button>{tx.status === 'CREATED' && !tx.is_demo && <button className="ml-2" disabled={recovering !== null} onClick={() => void recover(tx)}>{recovering === tx.id ? 'Verifying…' : 'Retry verification'}</button>}</td></tr>)}</tbody></table></div>}
    </section>
    {detailLoading && <p role="status">Loading transaction…</p>}
    {detail && <section className="rounded border bg-white p-4" aria-label="Transaction detail"><h3 className="font-semibold">Transaction #{detail.id}</h3><dl className="mt-3 space-y-2">{Object.entries(detail).map(([key, value]) => <div key={key} className="break-all"><dt className="font-medium">{key.replaceAll('_', ' ')}</dt><dd>{typeof value === 'boolean' ? String(value) : value ?? '—'}</dd></div>)}</dl><button className="mt-4" onClick={() => setDetail(null)}>Close details</button><Evidence key={detail.id} id={detail.id} /></section>}
    <Disputes />
  </main>
}

