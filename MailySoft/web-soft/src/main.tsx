import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
<<<<<<< Updated upstream
import { queryClient } from './lib/queryClient'
=======
<<<<<<< HEAD
=======
import { queryClient } from './lib/queryClient'
>>>>>>> 9f3cd4149619be4d5c604a117d939f7904aad547
>>>>>>> Stashed changes
import './index.css'
import App from './App'
import { queryClient } from './lib/queryClient'
import { tryRestoreSession } from './api/auth'

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
