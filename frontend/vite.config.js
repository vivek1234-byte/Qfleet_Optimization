import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The dev server proxies /api straight through to the FastAPI backend, so the
// browser only ever talks to one origin. No hard-coded http://localhost:8000 in
// the pages, and no CORS preflight to go wrong on stage.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: '127.0.0.1',
    proxy: {
      '/api': {
        target: process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/docs': { target: process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000' },
      '/openapi.json': { target: process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000' },
    },
  },
  preview: { port: 4173, host: '127.0.0.1' },
  build: {
    outDir: 'dist',
    sourcemap: true,
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        // Split the heavyweight libraries out of the app bundle so a code
        // change does not invalidate the vendor chunk in the browser cache.
        // Vite 8 bundles with rolldown, which takes a function here rather
        // than the object form older Vite accepted.
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (/[\\/]node_modules[\\/](recharts|d3-|victory-)/.test(id)) return 'charts'
          if (/[\\/]node_modules[\\/](react|react-dom|react-router|axios|scheduler)/.test(id)) {
            return 'vendor'
          }
          return undefined
        },
      },
    },
  },
})
