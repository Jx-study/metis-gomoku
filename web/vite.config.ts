import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  base: '/metis-gomoku/',
  plugins: [react()],
  // engine.mjs 是 ES module，Worker 也要以 module 打包
  worker: { format: 'es' },
})
