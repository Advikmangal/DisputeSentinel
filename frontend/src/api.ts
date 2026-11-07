let token = sessionStorage.getItem('payoutsentinel-token')
export const getToken = () => token
export function setToken(value: string | null) {
  token = value
  if (value) sessionStorage.setItem('payoutsentinel-token', value)
  else sessionStorage.removeItem('payoutsentinel-token')
}
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const originalToken = token
  const headers = new Headers(options.headers)
  if (options.body) headers.set('Content-Type', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(path, { ...options, headers })
  const body = await response.json().catch(() => null)
  if (response.status === 401 && path !== '/api/auth/login' && token === originalToken) {
    setToken(null); window.dispatchEvent(new Event('session-expired'))
  }
  if (!response.ok) throw new Error(typeof body?.detail === 'string' ? body.detail : body?.detail?.message || `Request failed (${response.status}).`)
  if (token !== originalToken) throw new Error('Session changed. Please sign in again.')
  return body as T
}
export type Transaction = { id: number; paypal_order_id: string; paypal_capture_id: string | null; amount: string; currency: string; status: string; payer_email: string | null; description: string; created_at: string; captured_at: string | null }
