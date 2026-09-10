import { defineConfig, devices } from '@playwright/test'

/**
 * Pruebas E2E (extremo a extremo) con Playwright: manejan un navegador real contra
 * la app corriendo, probando los flujos completos front + back.
 *
 * Requisitos para correrlas (`npm run test:e2e`):
 *   1. El BACKEND corriendo (Docker, :8000) — el proxy de Vite reenvía /api ahí.
 *   2. Los datos y usuarios demo sembrados, en este orden:
 *        docker compose exec backend python manage.py seed_planes
 *        docker compose exec backend python manage.py seed_finanzas
 *        docker compose exec backend python manage.py seed_e2e_user --platform
 *   3. Playwright levanta el FRONTEND él mismo, en su propio puerto (ver abajo).
 */

/**
 * PUERTO DEDICADO, y no es un detalle cosmético.
 *
 * El 2026-09-10 estos tests corrieron contra OTRA APLICACIÓN sin avisar. Tres proyectos
 * de esta máquina usan Vite y se pelean el rango 5173-5175 (Maily-Academia, Plataforma
 * POS y este). La combinación que lo hacía posible eran dos comportamientos razonables
 * por separado:
 *   · Vite, si su puerto está ocupado, salta al siguiente LIBRE en silencio.
 *   · Playwright, con `reuseExistingServer`, da por bueno cualquier cosa que responda
 *     en la URL esperada.
 * Resultado: los tests hablaban con Maily-Academia y fallaban con "no encuentro el campo
 * de correo", que parece un bug del login y no lo es. Diagnosticar eso cuesta media hora.
 *
 * El arreglo son tres piezas juntas, ninguna sobra:
 *   · Puerto FIJO y alto del rango, para no chocar con los otros proyectos: Vite arranca
 *     en 5173 y sube de uno en uno, así que los demás se quedan abajo.
 *   · `--strictPort`: Vite FALLA en vez de saltar de puerto a escondidas. Si algo ocupa
 *     este puerto, la corrida se detiene con un mensaje claro en vez de mentir.
 *   · `reuseExistingServer: false`: Playwright siempre arranca el suyo y lo mata al
 *     terminar. Nunca hereda el servidor de nadie.
 *
 * ⚠ EL PUERTO NO ES LIBRE: tiene que estar dentro de `_VITE_PORTS` de
 * backend/config/settings/development.py (hoy 5173-5180). El proxy de Vite reenvía el
 * header `Origin` al backend, y Django valida CSRF contra `CSRF_TRUSTED_ORIGINS`, que se
 * genera de ese rango. Un puerto fuera del rango hace que `POST /auth/refresh/` responda
 * un 403 de CSRF —página HTML de Django, no JSON de DRF— y la sesión no se recupera: los
 * tests rebotan a /login y el fallo parece un bug de la pantalla. Comprobado el
 * 2026-09-10 con el 5273. Si hace falta otro puerto, se amplía el rango del backend en el
 * mismo cambio.
 */
const PUERTO_E2E = 5179

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: 'list',
  use: {
    baseURL: `http://localhost:${PUERTO_E2E}`,
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `npm run dev -- --port ${PUERTO_E2E} --strictPort`,
    url: `http://localhost:${PUERTO_E2E}`,
    reuseExistingServer: false,
    timeout: 120_000,
  },
})
