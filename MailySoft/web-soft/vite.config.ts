import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        // Separa las librerías pesadas en chunks propios para que no inflen el
        // bundle inicial y se cacheen aparte. Como las páginas ya se cargan con
        // React.lazy, estos chunks solo bajan cuando se visita la ruta que los usa.
        manualChunks(id) {
          if (!id.includes('node_modules')) return
          if (id.includes('recharts') || id.includes('d3-')) return 'charts'
          if (id.includes('jspdf')) return 'pdf'
          if (id.includes('xlsx')) return 'xlsx'
          if (id.includes('framer-motion')) return 'motion'
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      // Imágenes subidas (avatares) servidas por Django en dev.
      '/media': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
