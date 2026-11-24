import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { api, getToken, setToken } from './api'
import Payments from './Payments'
import { Dashboard, EvidenceVault, Disputes } from './Workspace'
export default function App() {
  const [token, updateToken] = useState(getToken)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [signup, setSignup] = useState(false)
  const [confirmPassword, setConfirmPassword] = useState('')
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
    event.preventDefault(); setError('')
    if (signup && password !== confirmPassword) { setError('Passwords do not match.'); return }
    setBusy(true)
    try {
      const result = await api<{ access_token: string }>(signup ? '/api/auth/register' : '/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) })
      setToken(result.access_token); updateToken(result.access_token); setPassword(''); setConfirmPassword(''); setPage('Dashboard')
    } catch (e) { setError(e instanceof Error ? e.message : 'Sign in failed.') }
    finally { setBusy(false) }
  }
  function logout() { setToken(null); updateToken(null); setPassword(''); setError('') }
  return <div className="app-shell">
    {waking && <p role="status" aria-live="polite" className="notice">Waking up the server, this can take a minute</p>}
    <header className="app-header"><div className="header-inner"><div className="brand"><span className="brand-mark">P</span><div><h1>PayoutSentinel</h1><p>PAYMENT EVIDENCE WORKSPACE</p></div></div><div className="actions"><span className="badge">Sandbox only</span>{token && <button onClick={logout}>Log out</button>}</div></div></header>
    {token ? <div key={token}><nav className="app-nav" aria-label="Main navigation">{['Dashboard', 'Payments', 'Evidence Vault', 'Dispute Agent'].map(p => <button aria-current={page === p ? 'page' : undefined} className={page === p ? 'active' : ''} key={p} onClick={() => setPage(p)}>{p}</button>)}</nav>{page === 'Payments' ? <Payments /> : page === 'Evidence Vault' ? <EvidenceVault /> : page === 'Dispute Agent' ? <Disputes /> : <Dashboard navigate={setPage} />}</div> : <main className="login-layout"><section className="login-story"><p className="eyebrow">FROM PAYMENT TO PROOF</p><h2>Good work deserves<br />good evidence.</h2><p>Organize delivery records. Find the gaps. Prepare dispute responses with a source for every quotation.</p><div className="story-steps"><span>01 - Verify payment</span><span>02 - Build your evidence</span><span>03 - Review your response</span></div><p className="muted">A portfolio demo using PayPal Sandbox. No real money moves.</p></section><section className="card login-card"><h2>{signup ? 'Create your demo account' : 'Welcome back'}</h2><p className="muted">{signup ? 'Get your own workspace with three simulated sample transactions.' : 'Sign in to your merchant workspace.'}</p><form onSubmit={login} className="space-y-4"><label>Email<input type="email" autoComplete="username" maxLength={320} required value={email} onChange={e => setEmail(e.target.value)} /></label><label>Password<input type="password" autoComplete={signup ? "new-password" : "current-password"} minLength={signup ? 12 : 1} maxLength={signup ? 128 : 1024} required value={password} onChange={e => setPassword(e.target.value)} /></label>{signup && <><p className="muted">Use 12-128 characters. This demo does not verify email ownership or offer password reset. Use synthetic documents only; payments use the project's shared PayPal Sandbox.</p><label>Confirm password<input type="password" autoComplete="new-password" required minLength={12} maxLength={128} value={confirmPassword} onChange={e => setConfirmPassword(e.target.value)} /></label></>}{error && <p role="alert" className="error-box">{error}</p>}<button className="primary" disabled={busy} type="submit">{busy ? (signup ? 'Creating account.' : 'Signing in.') : (signup ? 'Create account & try demo' : 'Sign in ')}</button></form><p className="muted">{signup ? 'Already have an account?' : 'New here? Try the live demo.'}</p><button type="button" disabled={busy} onClick={() => { setSignup(!signup); setError(''); setPassword(''); setConfirmPassword('') }}>{signup ? 'Sign in instead' : 'Create an account'}</button></section></main>}
  </div>
}
