import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: './',
  root: '.',
  build: {
    outDir: 'dist/renderer',
    sourcemap: false,
  },
  server: {
    port: 3001,
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
