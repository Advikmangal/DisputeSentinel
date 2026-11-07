import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import ts from 'typescript'

test('JWT storage, authenticated requests, logout and expired-session handling', async () => {
  const storage = new Map()
  globalThis.sessionStorage = {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
    removeItem: key => storage.delete(key),
  }
  globalThis.window = new EventTarget()
  const source = await fs.readFile(new URL('../src/api.ts', import.meta.url), 'utf8')
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } })
  const { api, getToken, setToken } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
  setToken('synthetic-test-token')
  assert.equal(getToken(), sessionStorage.getItem('payoutsentinel-token'))
  globalThis.fetch = async (path, options) => {
    assert.equal(path, '/api/transactions')
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
