import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// El navegador ve un solo origen (el de Vite): /admin/api se reenvía al backend, así la cookie de sesión funciona
// sin CORS. En Docker PANEL_API=http://asistente:8000; sin Docker, el asistente publicado en el host (8100).
const api = process.env.PANEL_API ?? 'http://localhost:8100'

export default defineConfig({
  base: '/panel/',
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, 'src') } },
  server: {
    host: true,
    port: 5173,
    proxy: { '/admin/api': { target: api, changeOrigin: false } },
    watch: { usePolling: process.env.PANEL_POLLING === '1' },
  },
})
