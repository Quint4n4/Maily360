import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import * as Sentry from '@sentry/react'
import './index.css'
import App from './App'
import { queryClient } from './lib/queryClient'
import { tryRestoreSession } from './api/auth'

// Sentry (observabilidad de errores del frontend) — DORMIDO sin VITE_SENTRY_DSN;
// se activa en producción poniendo esa variable al construir. Sin PII (app de salud).
const sentryDsn = import.meta.env.VITE_SENTRY_DSN as string | undefined
if (sentryDsn) {
  Sentry.init({
    dsn: sentryDsn,
    environment:
      (import.meta.env.VITE_SENTRY_ENVIRONMENT as string | undefined) ?? import.meta.env.MODE,
    sendDefaultPii: false,
    tracesSampleRate: 0,
  })
}

// Restaurar sesión JWT desde cookie de refresh (si existe).
void tryRestoreSession()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
