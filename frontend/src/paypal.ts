type Buttons = { render: (element: HTMLElement) => Promise<void>; close: () => Promise<void> }
export type PayPal = { Buttons: (options: {
  style: { label: string }; createOrder: () => Promise<string>
  onApprove: (data: { orderID: string }) => Promise<void>
  onCancel: () => void; onError: (error: unknown) => void
}) => Buttons }
declare global { interface Window { paypal?: PayPal } }
let loading: Promise<PayPal> | null = null
export function loadPayPal(): Promise<PayPal> {
  if (window.paypal) return Promise.resolve(window.paypal)
  if (loading) return loading
  const id = import.meta.env.VITE_PAYPAL_CLIENT_ID
  if (!id || id.startsWith('replace-')) return Promise.reject(new Error('Set VITE_PAYPAL_CLIENT_ID to your Sandbox app client ID and restart Vite.'))
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
