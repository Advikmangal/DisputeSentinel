import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { api, getToken, setToken } from './api'
import Payments from './Payments'
export default function App() {
  const [token, updateToken] = useState(getToken)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [waking, setWaking] = useState(false)
  useEffect(() => {
    const waking = () => setWaking(true)
    const ready = () => setWaking(false)
    window.addEventListener('server-waking', waking)
    window.addEventListener('server-ready', ready)
    return () => {
      window.removeEventListener('server-waking', waking)
      window.removeEventListener('server-ready', ready)
    }
  }, [])
  useEffect(() => {
    const expired = () => { updateToken(null); setError('Your session expired. Please sign in again.') }
    window.addEventListener('session-expired', expired)
    return () => window.removeEventListener('session-expired', expired)
  }, [])
  async function login(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const result = await api<{ access_token: string }>('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) })
      setToken(result.access_token); updateToken(result.access_token); setPassword('')
    } catch (e) { setError(e instanceof Error ? e.message : 'Sign in failed.') }
    finally { setBusy(false) }
  }
  function logout() { setToken(null); updateToken(null); setPassword(''); setError('') }
  return <div className="min-h-screen bg-slate-50 text-slate-900">
    {waking && <p role="status" aria-live="polite" className="bg-amber-100 p-4 text-center">Waking up the server, this can take a minute</p>}
    <header className="border-b bg-white p-6"><div className="mx-auto flex max-w-5xl items-center justify-between"><div><h1 className="text-2xl font-bold">PayoutSentinel</h1><p className="text-sm">PayPal Sandbox only</p></div>{token && <button onClick={logout}>Log out</button>}</div></header>
    {token ? <Payments key={token} /> : <main className="mx-auto mt-12 max-w-sm rounded border bg-white p-6"><h2 className="mb-4 text-xl font-semibold">Merchant login</h2><form onSubmit={login} className="space-y-4"><label>Email<input type="email" autoComplete="username" required value={email} onChange={e => setEmail(e.target.value)} /></label><label>Password<input type="password" autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)} /></label>{error && <p role="alert" className="text-red-700">{error}</p>}<button disabled={busy} type="submit">{busy ? 'Signing in…' : 'Sign in'}</button></form></main>}
  </div>
}
