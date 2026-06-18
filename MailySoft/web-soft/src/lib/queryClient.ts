/**
 * queryClient — instancia única de TanStack Query para toda la app.
 *
 * Defaults pensados para una app clínica:
 *   - retry 1: ante un fallo de red reintenta una vez (sin machacar el backend).
 *   - No reintentar en errores 4xx (401/403/404): son definitivos, no de red.
 *   - staleTime 30s: evita refetches agresivos al cambiar de pestaña.
 */

import { QueryClient } from '@tanstack/react-query'
import { ApiError } from './http'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: (failureCount, error) => {
        if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false
        return failureCount < 1
      },
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: false,
    },
  },
})
