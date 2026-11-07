import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import ts from 'typescript'

for (const base of ['', 'https://api.example.invalid']) {
test(`API base ${base || 'local proxy'}: JWT storage, logout and expiry`, async () => {
  const storage = new Map()
  globalThis.sessionStorage = {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
    removeItem: key => storage.delete(key),
  }
  globalThis.window = new EventTarget()
  const source = await fs.readFile(new URL('../src/api.ts', import.meta.url), 'utf8')
  const { outputText } = ts.transpileModule(source.replace('import.meta.env.VITE_API_URL', JSON.stringify(base ? base + '/' : '')), { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } })
  const { api, getToken, setToken } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
  setToken('synthetic-test-token')
  assert.equal(getToken(), sessionStorage.getItem('payoutsentinel-token'))
  globalThis.fetch = async (path, options) => {
    if (path === `${base}/health`) return Response.json({ status: 'ok' })
    assert.equal(path, `${base}/api/transactions`)
    assert.equal(options.headers.get('Authorization'), 'Bearer synthetic-test-token')
    return Response.json({ items: [] })
  }
  assert.deepEqual(await api('/api/transactions'), { items: [] })
  let expired = false
  window.addEventListener('session-expired', () => { expired = true })
  globalThis.fetch = async () => Response.json({ detail: 'Expired' }, { status: 401 })
  await assert.rejects(api('/api/transactions'), /Expired/)
  assert.equal(expired, true)
  assert.equal(getToken(), null)
  assert.equal(sessionStorage.getItem('payoutsentinel-token'), null)
  setToken('another-synthetic-token')
  setToken(null)
  assert.equal(getToken(), null)
  assert.equal(storage.size, 0)
})

}

test('cold start retries health only, shares probe, and sends each requested operation once', async t => {
  globalThis.sessionStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  globalThis.window = new EventTarget()
  const realTimeout = globalThis.setTimeout
  t.mock.method(globalThis, 'setTimeout', (fn, ms, ...args) => realTimeout(fn, Math.min(ms, 5), ...args))
  const source = await fs.readFile(new URL('../src/api.ts', import.meta.url), 'utf8')
  const { outputText } = ts.transpileModule(source.replace('import.meta.env.VITE_API_URL', "''"), { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } })
  const { api } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}#cold-start`)
  let healthCalls = 0, mutationCalls = 0, waking = 0, ready = 0
  window.addEventListener('server-waking', () => waking++)
  window.addEventListener('server-ready', () => ready++)
  globalThis.fetch = async (path, options) => {
    if (path === '/health') {
      healthCalls++
      if (healthCalls === 1) throw new TypeError('Temporarily unavailable')
      if (healthCalls === 2) return new Response('Starting', { status: 503 })
      return Response.json({ status: 'ok' })
    }
    mutationCalls++
    assert.equal(options.method, 'POST')
    assert.equal(options.headers.get('Idempotency-Key'), 'test-key')
    return Response.json({ status: 'CREATED' })
  }
  await Promise.all([api('/api/payments/create-order', { method: 'POST', headers: { 'Idempotency-Key': 'test-key' } }), api('/api/payments/create-order', { method: 'POST', headers: { 'Idempotency-Key': 'test-key' } })])
  assert.equal(healthCalls, 3)
  assert.equal(mutationCalls, 2)
  assert.ok(waking > 0)
  assert.equal(ready, 1)
})

test('unavailable backend stops after bounded health retries; explicit retry recovers', async t => {
  globalThis.sessionStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  globalThis.window = new EventTarget()
  const realTimeout = globalThis.setTimeout
  t.mock.method(globalThis, 'setTimeout', (fn, ms, ...args) => realTimeout(fn, Math.min(ms, 5), ...args))
  const source = await fs.readFile(new URL('../src/api.ts', import.meta.url), 'utf8')
  const { outputText } = ts.transpileModule(source.replace('import.meta.env.VITE_API_URL', "''"), { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } })
  const { api } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}#unavailable`)
  let attempts = 0
  globalThis.fetch = async path => { assert.equal(path, '/health'); attempts++; return new Response('Starting', { status: 503 }) }
  await assert.rejects(api('/api/auth/login', { method: 'POST' }), /still unavailable/)
  assert.equal(attempts, 8)
  globalThis.fetch = async path => Response.json(path === '/health' ? { status: 'ok' } : { access_token: 'synthetic' })
  assert.deepEqual(await api('/api/auth/login', { method: 'POST' }), { access_token: 'synthetic' })
})
