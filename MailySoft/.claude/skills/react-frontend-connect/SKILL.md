---
name: react-frontend-connect
description: >
  Estándares y arquitectura para conectar un frontend React + Vite + TypeScript a un backend
  Django REST Framework (Maily Soft). Úsala SIEMPRE que se escriba, revise o audite código de
  frontend que: consume la API, maneja autenticación/tokens JWT, gestiona estado de servidor,
  define tipos de la API, controla acceso por rol en la UI, o cualquier conexión front↔back.
  Hace cumplir: cliente HTTP tipado, manejo seguro de tokens, refresh automático, TanStack Query,
  TypeScript estricto, tipos generados del OpenAPI, manejo de 401/403, y seguridad (XSS, sin
  secretos en el bundle, el backend es la autoridad de permisos).
---

# React + Vite + TypeScript ↔ Django REST — Estándares de conexión

Eres un ingeniero frontend senior especializado en React 18 + Vite + TypeScript conectando a APIs
Django REST Framework con JWT. Aplica estas reglas SIN EXCEPCIÓN.

## Reglas de oro (las 4 innegociables)

1. **El backend es la AUTORIDAD de permisos.** Los checks de rol en el frontend son SOLO UX
   (ocultar botones, redirigir). NUNCA son seguridad: el backend ya devuelve 403. Jamás asumas
   que "como oculté el botón, está protegido".
2. **CERO secretos en el frontend.** Todo lo que va al bundle es público. Nada de API keys de
   terceros, tokens de servicio, ni credenciales. Solo `VITE_API_URL` y config pública.
3. **TypeScript estricto, sin `any`.** Los tipos de la API se derivan del OpenAPI del backend
   (o se escriben a mano y se mantienen sincronizados). `tsconfig` con `strict: true`.
4. **Toda llamada al backend pasa por el cliente HTTP central.** Nunca `fetch()` suelto en un
   componente. Un solo lugar maneja base URL, headers, tokens, refresh y errores.

## Arquitectura de capas (frontend)

```
Componente (UI)
   └─ hook de datos (useQuery/useMutation de TanStack Query)
        └─ función de API tipada (src/api/<dominio>.ts)
             └─ cliente HTTP central (src/lib/http.ts) — base URL, auth, refresh, errores
                  └─ backend DRF (/api/v1/...)
```

- **Componente**: solo presentación + interacción. Llama a hooks, no a `fetch`.
- **Hook**: `useQuery`/`useMutation`; maneja loading/error/cache.
- **Función de API**: tipada (input y output), una por endpoint. Devuelve datos, no respuestas crudas.
- **Cliente HTTP**: el único que toca `fetch`/axios, tokens y la base URL.

## Configuración de entorno

- `VITE_API_URL` en `.env` (NO commitear `.env`; sí `.env.example`). En Vite las vars públicas
  empiezan con `VITE_`.
- Acceso vía `import.meta.env.VITE_API_URL`. Nunca hardcodear `http://localhost:8000`.

```
# .env.example
VITE_API_URL=http://localhost:8000/api/v1
```

## Cliente HTTP central (`src/lib/http.ts`)

Responsabilidades: base URL, JSON, adjuntar el access token, refrescar en 401, normalizar errores.

```ts
const BASE = import.meta.env.VITE_API_URL as string

export class ApiError extends Error {
  constructor(public status: number, public detail: string, public body?: unknown) {
    super(detail)
  }
}

async function request<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const access = tokenStore.getAccess()
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(access ? { Authorization: `Bearer ${access}` } : {}),
      ...init.headers,
    },
  })

  if (res.status === 401 && retry && tokenStore.getRefresh()) {
    const ok = await refreshAccessToken()      // intenta /auth/refresh/
    if (ok) return request<T>(path, init, false) // reintenta UNA vez
    tokenStore.clear(); redirectToLogin()
    throw new ApiError(401, 'Sesión expirada')
  }
  if (res.status === 403) throw new ApiError(403, 'No tienes permiso para esta acción')
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new ApiError(res.status, extractDetail(body), body)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const http = {
  get:  <T>(p: string) => request<T>(p),
  post: <T>(p: string, b: unknown) => request<T>(p, { method: 'POST', body: JSON.stringify(b) }),
  patch:<T>(p: string, b: unknown) => request<T>(p, { method: 'PATCH', body: JSON.stringify(b) }),
  del:  <T>(p: string) => request<T>(p, { method: 'DELETE' }),
}
```

Reglas del cliente:
- **Refresh automático en 401, reintento UNA sola vez**, y si falla → limpiar tokens + redirigir a login.
- **No tragues el 403**: propágalo para que la UI muestre "sin permiso" (el backend ya lo bloqueó).
- Normaliza el error de DRF (`{detail: "..."}` o `{campo: ["..."]}`) a un `ApiError` legible.

## Manejo de tokens JWT (seguridad)

DRF SimpleJWT devuelve `{access, refresh}` en el login. **Dónde guardarlos es una decisión de seguridad:**

| Estrategia | XSS | Simplicidad | Recomendación |
|---|---|---|---|
| `localStorage` | ❌ vulnerable a XSS (script malicioso lee el token) | fácil | Aceptable en MVP SI el frontend está libre de XSS y sin `dangerouslySetInnerHTML` |
| `sessionStorage` | ❌ igual que localStorage, pero se borra al cerrar pestaña | fácil | Para "no recordarme" |
| Memoria (variable) + refresh en cookie httpOnly | ✅ el access no es accesible por JS | requiere backend que ponga cookie httpOnly | Lo más seguro; ideal para producción |

- **MVP**: `localStorage` (recordarme) / `sessionStorage` (sesión) es aceptable **si y solo si** el frontend no tiene vectores XSS (ver sección Seguridad). Documenta el riesgo.
- **Producción endurecida**: mover el refresh token a cookie `httpOnly` + `Secure` + `SameSite`, y el access token en memoria.
- **NUNCA** loguees tokens (`console.log(token)`), ni los pongas en la URL.
- **Logout**: limpiar tokens + (idealmente) blacklist del refresh en el backend (`/auth/...`).

```ts
// src/lib/tokenStore.ts — un solo lugar que toca el storage
const ACCESS = 'maily.access', REFRESH = 'maily.refresh'
export const tokenStore = {
  getAccess:  () => storage().getItem(ACCESS),
  getRefresh: () => storage().getItem(REFRESH),
  set: (a: string, r: string) => { storage().setItem(ACCESS, a); storage().setItem(REFRESH, r) },
  clear: () => { localStorage.removeItem(ACCESS); localStorage.removeItem(REFRESH); sessionStorage.removeItem(ACCESS); sessionStorage.removeItem(REFRESH) },
}
```

## Flujo de autenticación

1. **Login**: `POST /auth/login/` con `{email, password}` → `{access, refresh}`. Guardar tokens.
2. **Perfil**: inmediatamente `GET /me/` → `{ active_role, active_tenant, memberships, is_platform_staff }`.
   **El rol REAL viene de aquí**, no de un valor hardcodeado. Poblar el contexto de rol con `active_role`.
3. **Rutas protegidas**: un `<RequireAuth>` que redirige a `/login` si no hay token o `/me/` falla.
4. **Panel por rol**: decidir qué pintar según `active_role` (o `is_platform_staff` para el panel SaaS).
5. **Logout**: limpiar tokens + redirigir a login.

> Migrar el `RoleContext` que hoy hardcodea el rol → poblarlo desde la respuesta de `/me/`.

## Estado de servidor: TanStack Query

Usa `@tanstack/react-query` para todo dato que venga del backend (no `useState`+`useEffect` a mano).
Da cache, loading, error, refetch e invalidación gratis.

```ts
// src/api/pacientes.ts
export const pacientesApi = {
  list:   (search = '') => http.get<Paginated<Patient>>(`/pacientes/?search=${encodeURIComponent(search)}`),
  create: (data: PatientInput) => http.post<Patient>('/pacientes/', data),
  detail: (id: string) => http.get<Patient>(`/pacientes/${id}/`),
}

// hook
export const usePacientes = (search: string) =>
  useQuery({ queryKey: ['pacientes', search], queryFn: () => pacientesApi.list(search) })

export const useCrearPaciente = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: pacientesApi.create,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['pacientes'] }),
  })
}
```

## Tipos de la API

- **Preferido**: generar tipos TypeScript del OpenAPI del backend (`/api/schema/`) con `openapi-typescript`.
  Un cambio en el backend → regenerar → el frontend deja de compilar si algo no cuadra.
- **Alternativa**: tipos a mano en `src/types/api.ts`, mantenidos en sync con el backend. Documentar.
- Los tipos reflejan EXACTO lo que el backend devuelve (revisar los serializers / `/api/docs/`).

## Manejo de errores en la UI

- **401**: el cliente HTTP ya refresca/redirige. La UI no lo maneja salvo el redirect.
- **403**: mostrar un mensaje claro ("No tienes permiso para esta acción") — no romper la pantalla.
  Idealmente el frontend YA oculta esa acción por rol, pero el 403 es la red de seguridad.
- **400 (validación)**: mapear `{campo: ["error"]}` de DRF a los campos del formulario.
- **5xx / red**: mensaje genérico + opción de reintentar. Nunca mostrar el stack al usuario.
- Estados de carga y vacío en cada lista (skeleton/spinner + "sin resultados").

## Seguridad del frontend (checklist OWASP)

- **XSS**: React escapa por defecto. PROHIBIDO `dangerouslySetInnerHTML` con contenido del backend
  o del usuario sin sanitizar. Cuidado con `href`/`src` que vengan de datos (no `javascript:`).
- **Tokens**: nunca en logs, ni en la URL, ni en mensajes de error. Limpiar en logout.
- **Sin secretos en el bundle**: nada sensible en `VITE_*` (todo lo `VITE_` es público).
- **HTTPS en producción**: el `VITE_API_URL` de prod debe ser `https://`.
- **CORS**: lo controla el backend; el front solo usa el origen permitido.
- **Permisos = UX, no seguridad**: el ocultar un botón no protege el endpoint. El backend manda.
- **Dependencias**: `npm audit` en CI; no introducir libs sin revisar.
- **CSP**: en producción, cabecera Content-Security-Policy (la sirve el host/CDN).
- **Auto-logout**: ante 401 persistente, limpiar sesión.

## Auditoría de conexiones front↔back (qué revisar)

Cuando audites el frontend o sus conexiones, verifica:
1. ¿Hay `fetch()`/axios sueltos en componentes (fuera del cliente central)? → bug.
2. ¿El rol se lee de `/me/` o sigue hardcodeado? → debe venir del backend.
3. ¿Se maneja el 401 (refresh+redirect) y el 403 (mensaje) en todos los flujos?
4. ¿Hay tokens en `console.log`, en la URL, o en el código? → fuga.
5. ¿Hay `dangerouslySetInnerHTML` o `href`/`src` con datos sin sanitizar? → XSS.
6. ¿Los tipos de la API coinciden con los serializers del backend? → desincronización.
7. ¿Las listas están paginadas (no asumen array completo)? El backend pagina.
8. ¿Se asume que el rol del front basta para seguridad? → no; el backend es la autoridad.
9. ¿`.env` está en `.gitignore` y no hay URLs/secrets hardcodeados?
10. ¿Los formularios mapean los errores 400 de DRF a sus campos?

## Estructura de archivos recomendada

```
src/
  lib/
    http.ts          ← cliente HTTP central (único que toca fetch+tokens)
    tokenStore.ts    ← único acceso al storage de tokens
    queryClient.ts   ← config de TanStack Query
  api/
    auth.ts          ← login, refresh, me
    pacientes.ts  personal.ts  agenda.ts  audit.ts
  types/
    api.ts           ← tipos (generados del OpenAPI o a mano)
  auth/
    AuthContext.tsx  ← user + role (poblado desde /me/), login/logout
    RequireAuth.tsx  ← guard de rutas
    permisos.ts      ← matriz de rol (UX); refleja la del backend
  hooks/             ← useQuery/useMutation por dominio
  pages/  components/ ← UI (sin fetch directo)
```

## Lo que NUNCA haces
- `fetch()` directo en un componente.
- Confiar en el rol del frontend para seguridad (el backend es la autoridad).
- Guardar/loguear tokens de forma insegura, o ponerlos en la URL.
- `any` en tipos de la API. `dangerouslySetInnerHTML` con datos no confiables.
- Hardcodear la URL del backend o cualquier secreto.
- Asumir que una lista viene completa (el backend pagina).
