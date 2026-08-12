import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/demo/',
  server: {
    port: 5173,
    proxy: {
      '/demo-api': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
    },
  },
  build: { outDir: 'dist' },
  test: {
    pool: 'threads',
    maxWorkers: 1,
    isolate: false,
    fileParallelism: false,
  },
})
