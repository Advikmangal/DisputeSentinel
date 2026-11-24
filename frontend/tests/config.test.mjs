import test from 'node:test'
import assert from 'node:assert/strict'
import { loadConfigFromFile } from 'vite'
import { fileURLToPath } from 'node:url'

test('Render builds validate and normalize the API origin', async () => {
  const previous = { RENDER: process.env.RENDER, VITE_API_URL: process.env.VITE_API_URL }
  try {
    process.env.RENDER = 'true'
    const configPath = fileURLToPath(new URL('../vite.config.ts', import.meta.url))
    for (const value of ['', 'https://api.example.com/api', 'http://api.example.com', 'https://api.example.invalid', 'https://user:secret@api.example.com']) {
      process.env.VITE_API_URL = value
      await assert.rejects(loadConfigFromFile({ command: 'build', mode: 'test' }, configPath, undefined, 'silent'), /VITE_API_URL/)
    }
    process.env.VITE_API_URL = ' https://api.example.com/ '
    const result = await loadConfigFromFile({ command: 'build', mode: 'test' }, configPath, undefined, 'silent')
    assert.equal(result.config.define['import.meta.env.VITE_API_URL'], '"https://api.example.com"')
    delete process.env.RENDER
    process.env.VITE_API_URL = ''
    assert.ok(await loadConfigFromFile({ command: 'serve', mode: 'test' }, configPath, undefined, 'silent'))
  } finally {
    for (const [name, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[name]
      else process.env[name] = value
    }
  }
})
