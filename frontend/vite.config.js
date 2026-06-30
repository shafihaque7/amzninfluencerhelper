import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/scrape': {
        target: 'http://127.0.0.1:5000',
        timeout: 600000,
        proxyTimeout: 600000,
      },
      '/health': 'http://127.0.0.1:5000',
    },
  },
})
