import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Forward /api to Flask so the browser sees one origin: no CORS issues,
    // and localhost vs. 127.0.0.1 doesn't matter.
    proxy: {
      '/api': 'http://127.0.0.1:5001',
    },
  },
})
