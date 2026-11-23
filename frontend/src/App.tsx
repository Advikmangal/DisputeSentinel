import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { api, getToken, setToken } from './api'
import Payments from './Payments'
import { Dashboard, EvidenceVault, Disputes } from './Workspace'
export default function App() {
  const [token, updateToken] = useState(getToken)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [waking, setWaking] = useState(false)
  const [page, setPage] = useState('Dashboard')
  useEffect(() => {
    const wake = () => setWaking(true), ready = () => setWaking(false)
    const expired = () => { updateToken(null); setError('Your session expired. Please sign in again.') }
    window.addEventListener('server-waking', wake)
    window.addEventListener('server-ready', ready)
    window.addEventListener('session-expired', expired)
    return () => { window.removeEventListener('server-waking', wake); window.removeEventListener('server-ready', ready); window.removeEventListener('session-expired', expired) }
  }, [])
  async function login(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const result = await api<{ access_token: string }>('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) })
      setToken(result.access_token); updateToken(result.access_token); setPassword(''); setPage('Dashboard')
    } catch (e) { setError(e instanceof Error ? e.message : 'Sign in failed.') }
    finally { setBusy(false) }
  }
  function logout() { setToken(null); updateToken(null); setPassword(''); setError('') }
  return <div className="app-shell">
    {waking && <p role="status" aria-live="polite" className="notice">Waking up the server, this can take a minute</p>}
    <header className="app-header"><div className="header-inner"><div className="brand"><span className="brand-mark">P</span><div><h1>PayoutSentinel</h1><p>PAYMENT EVIDENCE WORKSPACE</p></div></div><div className="actions"><span className="badge">Sandbox only</span>{token && <button onClick={logout}>Log out</button>}</div></div></header>
    {token ? <div key={token}><nav className="app-nav" aria-label="Main navigation">{['Dashboard', 'Payments', 'Evidence Vault', 'Dispute Agent'].map(p => <button aria-current={page === p ? 'page' : undefined} className={page === p ? 'active' : ''} key={p} onClick={() => setPage(p)}>{p}</button>)}</nav>{page === 'Payments' ? <Payments /> : page === 'Evidence Vault' ? <EvidenceVault /> : page === 'Dispute Agent' ? <Disputes /> : <Dashboard navigate={setPage} />}</div> : <main className="login-layout"><section className="login-story"><p className="eyebrow">FROM PAYMENT TO PROOF</p><h2>Good work deserves<br />good evidence.</h2><p>Organize delivery records. Find the gaps. Prepare dispute responses with a source for every quotation.</p><div className="story-steps"><span>01 · Verify payment</span><span>02 · Build your evidence</span><span>03 · Review your response</span></div><p className="muted">A portfolio demo using PayPal Sandbox. No real money moves.</p></section><section className="card login-card"><h2>Welcome back</h2><p className="muted">Sign in to your merchant workspace.</p><form onSubmit={login} className="space-y-4"><label>Email<input type="email" autoComplete="username" required value={email} onChange={e => setEmail(e.target.value)} /></label><label>Password<input type="password" autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)} /></label>{error && <p role="alert" className="error-box">{error}</p>}<button className="primary" disabled={busy} type="submit">{busy ? 'Signing in…' : 'Sign in →'}</button></form></section></main>}
  </div>
}
