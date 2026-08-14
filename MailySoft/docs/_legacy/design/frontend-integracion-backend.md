# Plan de Integración Frontend ↔ Backend — Maily Soft

> Fecha: 2026-06-05 · Estado: plan de trabajo aprobable
> Conectar `web-soft` (React + Vite) con el backend DRF que ya corre en `/api/v1/`.

## 1. Punto de partida

**Frontend (`web-soft/`):** React 18 + Vite + TS + Tailwind + react-router-dom + framer-motion.
UI muy avanzada (Login, Agenda, Pacientes, Personal, Finanzas + panel de plataforma), pero:
- Todo usa **datos mock** (`src/data/`).
- El **rol está hardcodeado** en `admin` (`RoleContext`).
- **No hay capa de API** (sin axios/fetch central, sin TanStack Query).
- **No hay `.env`** (falta `VITE_API_URL`).

**Backend (listo):** JWT (`/auth/login`, `/auth/refresh`), `/me/`, pacientes, personal, agenda, audit.
Permisos por rol (403), aislamiento multi-tenant (404), CORS ya permite `localhost:5173`.

**Lo bueno:** la matriz de permisos del front (`auth/permisos.ts`) **ya coincide** con los 7 roles del backend. Solo hay que alimentarla con el rol real de `/me/`.

## 2. Estrategia

- **Vertical slice por pantalla**: conectar una pantalla completa de punta a punta antes de pasar a la siguiente, empezando por **Login → /me/ → Pacientes** (la más simple y demostrable).
- **No reescribir la UI**: solo reemplazar la fuente de datos (mock → API) y poblar el rol real.
- Aplicar la skill `react-frontend-connect` en cada pieza.
- Decisiones de seguridad documentadas (almacenamiento de tokens).

## 3. Dependencias a agregar

```bash
cd web-soft
npm i @tanstack/react-query        # estado de servidor (cache/loading/error)
npm i -D openapi-typescript        # generar tipos del OpenAPI del backend (opcional pero recomendado)
```
(axios es opcional; con `fetch` envuelto basta. Mantener el bundle ligero.)

## 4. Fases de implementación

### Fase 0 — Cimiento de conexión (1 entrega)
La plomería que todo lo demás usa. **No toca pantallas todavía.**
1. `.env` + `.env.example` con `VITE_API_URL=http://localhost:8000/api/v1`.
2. `src/lib/tokenStore.ts` — único acceso al storage de tokens.
3. `src/lib/http.ts` — cliente HTTP central: base URL, JSON, Bearer, **refresh en 401 (reintento único)**, normalización de errores DRF, propaga 403.
4. `src/lib/queryClient.ts` + envolver la app en `<QueryClientProvider>`.
5. `src/api/auth.ts` — `login()`, `refreshAccessToken()`, `me()`.
6. `src/types/api.ts` — tipos (generados del OpenAPI o a mano: `Patient`, `Appointment`, `Doctor`, `Me`, `Paginated<T>`...).

**Gate:** desde la consola del navegador o un botón temporal, `login()` real devuelve tokens y `me()` devuelve el perfil.

### Fase 1 — Login + sesión + rol real (1 entrega)
1. `src/auth/AuthContext.tsx` — guarda user + rol (de `/me/`), expone `login/logout/isLoading`.
2. Conectar `LoginPage`: `POST /auth/login/` → guardar tokens → `GET /me/` → set rol → navegar según rol (`active_role` / `is_platform_staff`).
3. `src/auth/RequireAuth.tsx` — guard de rutas: sin token o `/me/` falla → `/login`.
4. Migrar `RoleContext` para que el rol venga de `AuthContext` (no hardcodeado).
5. Logout: limpiar tokens + redirigir.

**Gate:** login real con `recepcion@vitalis.mx` entra y el menú/panel refleja su rol real (recepción, no admin).

### Fase 2 — Pacientes de punta a punta (1 entrega)
1. `src/api/pacientes.ts` (list/create/detail/update/deactivate) + hooks TanStack Query.
2. `ContactosPage`: reemplazar mock por `usePacientes()`; estados de carga/vacío/error.
3. `NuevoPacienteDrawer`: `useCrearPaciente()`; mapear errores 400 de DRF a los campos (CURP/teléfono).
4. `ExpedienteDrawer`: cargar el detalle real (dispara `PATIENT_READ` en la bitácora).
5. Manejo de 403 (si el rol no puede crear): mostrar mensaje, no romper.

**Gate:** crear/buscar/ver pacientes reales; un usuario de recepción funciona, uno de solo-lectura ve pero no crea.

### Fase 3 — Personal + Agenda (2 entregas)
- `src/api/personal.ts` + `PersonalPage`, drawers de doctor/consultorio, modal de config.
- `src/api/agenda.ts` + `AgendaPage` (calendario real), `CrearEventoModal`, `DetalleCitaModal`, cambio de estado, reagendar. Manejar el error de anti-empalme (cita encimada → mensaje claro).

**Gate:** agendar una cita real, cambiar su estado, ver que el recordatorio se programa (en backend).

### Fase 4 — Panel de plataforma (cuando exista backend)
El panel SaaS (`pages/plataforma/`) consume endpoints que **aún no existen** en el backend (métricas, clínicas, billing). Queda **bloqueado** hasta construir esos endpoints. Mientras, puede quedar con mock.

## 5. Decisión TOMADA: almacenamiento de tokens — HÍBRIDO (memoria + httpOnly)

**Decisión (2026-06-05):** patrón híbrido, lo más seguro, desde el inicio.
- **Access token** → en **memoria** (variable JS, no localStorage). Vida corta (15 min). Se pierde al
  recargar, pero se recupera con el refresh. No es robable por XSS persistente.
- **Refresh token** → en **cookie `HttpOnly` + `Secure` + `SameSite=Strict`**. JavaScript NO lo lee →
  protegido de XSS. El navegador la envía sola en `/auth/refresh/` y `/auth/logout/`.

### Implicaciones (el backend cambia ANTES que el frontend)

| # | Lado | Cambio |
|---|---|---|
| 1 | Backend | `POST /auth/login/` devuelve `{access}` en el JSON y pone el refresh en cookie httpOnly (no en el body). |
| 2 | Backend | `POST /auth/refresh/` lee el refresh de la cookie (no del body) → devuelve `{access}` nuevo. |
| 3 | Backend | `POST /auth/logout/` borra la cookie + blacklist del refresh (SimpleJWT token_blacklist ya está). |
| 4 | Backend | **Protección CSRF**: como ahora hay cookies, se requiere mitigar CSRF — `SameSite=Strict` en la cookie + (si aplica) token CSRF en mutaciones. Documentar el enfoque. |
| 5 | Backend | CORS con credenciales: `CORS_ALLOW_CREDENTIALS=True` (ya) + el front manda `credentials: 'include'`. Afinar `CSRF_TRUSTED_ORIGINS` / `CORS_ALLOWED_ORIGINS`. |
| 6 | Frontend | Cliente HTTP: access en memoria; en 401 → `POST /auth/refresh/` (la cookie viaja sola) → reintento; `credentials: 'include'` en todas las llamadas. |

### Flujo resultante
```
login    → {access} en memoria + cookie httpOnly (refresh)
llamadas → Authorization: Bearer <access en memoria>
recargar → /auth/refresh/ (cookie) → nuevo access → sesión recuperada sin re-login
logout   → /auth/logout/ borra cookie + blacklist
```

> **Trade-off asumido:** httpOnly elimina el riesgo de robo de token por XSS, pero introduce el riesgo
> de CSRF (las cookies se envían solas). Se mitiga con `SameSite=Strict` + protección CSRF en mutaciones.
> Es el estándar de la industria para apps con datos sensibles.

**Orden de trabajo:** primero los cambios de backend (pasos 1-5, con el flujo de agentes engineer→tester→reviewer→security), luego el frontend (paso 6) consume el nuevo flujo.

## 6. Lo que NO cambia
- La UI, los estilos, las animaciones — se conservan.
- La matriz de permisos del front (`permisos.ts`) — se conserva (solo se alimenta con el rol real).
- El panel de plataforma — espera a su backend.

## 7. Pendientes / riesgos
- **El rol del front es UX, no seguridad**: el backend ya devuelve 403; el front solo mejora la experiencia.
- **Tipos sincronizados**: si se generan del OpenAPI, regenerar tras cada cambio del backend.
- **Token storage**: migrar a httpOnly antes de producción real.
- **Panel de plataforma**: bloqueado hasta tener endpoints de métricas/billing.
