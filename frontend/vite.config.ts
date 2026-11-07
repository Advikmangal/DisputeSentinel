import { defineConfig } from 'vite'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  envDir: '..',
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  plugins: [tailwindcss()],
})
