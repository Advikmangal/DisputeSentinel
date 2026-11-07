let token = sessionStorage.getItem('payoutsentinel-token')
const apiBase = (import.meta.env.VITE_API_URL || '').replace(/\/+$/, '')
let readyUntil = 0
let wakePromise: Promise<void> | null = null
async function ensureServerAwake() {
  if (Date.now() < readyUntil) return
  if (wakePromise) return wakePromise
  wakePromise = (async () => {
    const notice = setTimeout(() => window.dispatchEvent(new Event('server-waking')), 2000)
    try {
      for (let attempt = 0; attempt < 8; attempt++) {
        const controller = new AbortController()
        const timeout = setTimeout(() => controller.abort(), 10000)
        try {
          const response = await fetch(`${apiBase}/health`, { signal: controller.signal, cache: 'no-store' })
          if (response.ok && (await response.json()).status === 'ok') {
            readyUntil = Date.now() + 10 * 60 * 1000
            return
          }
        } catch { /* Cold starts may time out or return a temporary HTML response. */ }
        finally { clearTimeout(timeout) }
        window.dispatchEvent(new Event('server-waking'))
        // Even immediate proxy/CORS failures must leave time for a minute-long wake-up.
        if (attempt < 7) await new Promise(resolve => setTimeout(resolve, 10000))
      }
      throw new Error('The server is still unavailable. Please try again shortly.')
    } finally {
      clearTimeout(notice)
      window.dispatchEvent(new Event('server-ready'))
    }
  })()
  try { await wakePromise } finally { wakePromise = null }
}
export const getToken = () => token
export function setToken(value: string | null) {
  token = value
  if (value) sessionStorage.setItem('payoutsentinel-token', value)
  else sessionStorage.removeItem('payoutsentinel-token')
}
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const originalToken = token
  await ensureServerAwake()
  if (token !== originalToken) throw new Error('Session changed. Please sign in again.')
  const headers = new Headers(options.headers)
  if (options.body) headers.set('Content-Type', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(`${apiBase}${path}`, { ...options, headers })
  const body = await response.json().catch(() => null)
  if (response.status === 401 && path !== '/api/auth/login' && token === originalToken) {
    setToken(null); window.dispatchEvent(new Event('session-expired'))
  }
  if (!response.ok) throw new Error(typeof body?.detail === 'string' ? body.detail : body?.detail?.message || `Request failed (${response.status}).`)
  if (token !== originalToken) throw new Error('Session changed. Please sign in again.')
  return body as T
}
export type Transaction = { is_demo: boolean; id: number; paypal_order_id: string; paypal_capture_id: string | null; amount: string; currency: string; status: string; payer_email: string | null; description: string; created_at: string; captured_at: string | null }
