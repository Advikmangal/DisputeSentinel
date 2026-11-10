import { api } from './api'
type Buttons = { render: (element: HTMLElement) => Promise<void>; close: () => Promise<void> }
export type PayPal = { Buttons: (options: {
  style: { label: string }; createOrder: () => Promise<string>
  onApprove: (data: { orderID: string }) => Promise<void>
  onCancel: () => void; onError: (error: unknown) => void
}) => Buttons }
declare global { interface Window { paypal?: PayPal } }
let loading: Promise<PayPal> | null = null
export async function loadPayPal(): Promise<PayPal> {
  if (window.paypal) return Promise.resolve(window.paypal)
  if (loading) return loading
  const { client_id: id } = await api<{ client_id: string }>('/api/payments/config')
  if (loading) return loading
  if (!id) throw new Error('PayPal is not configured on the server.')
  loading = new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = `https://www.sandbox.paypal.com/sdk/js?client-id=${encodeURIComponent(id)}&currency=USD&intent=capture&components=buttons`
    script.async = true
    const timer = window.setTimeout(() => fail(), 20000)
    function fail() { clearTimeout(timer); script.remove(); loading = null; reject(new Error('PayPal could not load. Check your connection and Sandbox client ID.')) }
    script.onerror = fail
    script.onload = () => { clearTimeout(timer); if (window.paypal) resolve(window.paypal); else fail() }
    document.head.append(script)
  })
  return loading
}

