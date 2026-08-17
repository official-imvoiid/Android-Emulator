import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const BACKEND = 'http://127.0.0.1:8765'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // The backend owns /api and /ws; everything else is the React app.
    proxy: {
      '/api': { target: BACKEND, changeOrigin: true },
      '/ws': { target: BACKEND, ws: true, changeOrigin: true },
    },
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
