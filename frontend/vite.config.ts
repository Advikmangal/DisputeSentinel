import { defineConfig, loadEnv } from 'vite'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, '..', 'VITE_')
  const apiUrl = (env.VITE_API_URL || '').trim().replace(/\/+$/, '')
  if (command === 'build' && process.env.RENDER === 'true' && !apiUrl) {
    throw new Error('Set VITE_API_URL to the API HTTPS origin in Render, then rebuild the frontend.')
  }
  if (apiUrl) {
    let valid = false
    try {
      const url = new URL(apiUrl)
      valid = url.protocol === 'https:' && url.origin === apiUrl && !url.hostname.endsWith('.invalid')
    } catch { /* Report the setting name without logging the supplied value. */ }
    if (!valid) throw new Error('VITE_API_URL must be the API HTTPS origin only, without /api, credentials, query or placeholder domain.')
  }
  return {
    envDir: '..',
    define: { 'import.meta.env.VITE_API_URL': JSON.stringify(apiUrl) },
    server: { proxy: { '/api': 'http://127.0.0.1:8000', '/health': 'http://127.0.0.1:8000', '/ready': 'http://127.0.0.1:8000' } },
    plugins: [tailwindcss()],
  }
})

