# Plan de Pruebas de Seguridad — Frontend Maily Soft (web-soft)

> Fecha: 2026-06-05 · Qué auditar en el frontend y sus conexiones al backend.
> Complementa la skill `react-frontend-connect`. Se corre antes de conectar datos reales.

## Principio rector

> **El frontend NO es la frontera de seguridad — el backend lo es.** El backend ya hace cumplir
> permisos por rol (403), aislamiento multi-tenant (404), validación y auditoría. La seguridad del
> frontend se enfoca en: no filtrar tokens/secretos, no abrir XSS, y manejar correctamente la sesión.
> Ocultar un botón por rol es UX, no protección.

## Checklist de auditoría (por categoría)

### 1. Manejo de tokens / sesión
- [ ] Los tokens NO aparecen en `console.log`, ni en mensajes de error, ni en la URL.
- [ ] El access token se adjunta solo vía el cliente HTTP central (`Authorization: Bearer`), no a mano.
- [ ] En 401, el cliente refresca UNA vez; si falla, limpia tokens y redirige a login (sin loop infinito).
- [ ] Logout limpia `localStorage` Y `sessionStorage` (ambos), y redirige.
- [ ] Decisión de almacenamiento documentada (localStorage MVP vs cookie httpOnly prod) con su riesgo.
- [ ] El refresh token no se usa para llamadas normales (solo para `/auth/refresh/`).

### 2. XSS (Cross-Site Scripting)
- [ ] CERO `dangerouslySetInnerHTML` con datos del backend o del usuario. Si existe, sanitizado (DOMPurify).
- [ ] `href`/`src` que vengan de datos no permiten `javascript:` ni `data:` peligrosos.
- [ ] No hay `eval`, `new Function`, ni inyección de `<script>` dinámico.
- [ ] El contenido de la bitácora / nombres / notas se renderiza como texto (React escapa por defecto).

### 3. Secretos en el bundle
- [ ] No hay API keys de terceros, tokens de servicio ni credenciales en el código (todo `VITE_*` es PÚBLICO).
- [ ] `.env` está en `.gitignore`; solo `.env.example` versionado.
- [ ] No hay URLs de backend hardcodeadas (todo desde `import.meta.env.VITE_API_URL`).
- [ ] `grep` por "password", "secret", "token", "key", "Bearer " en `src/` no revela nada sensible.

### 4. Conexión y errores
- [ ] Todas las llamadas pasan por el cliente HTTP central (sin `fetch()` suelto en componentes).
- [ ] El 403 se muestra como mensaje ("sin permiso"), no rompe la pantalla ni expone detalles.
- [ ] El 400 de DRF se mapea a los campos del formulario (no se muestra JSON crudo al usuario).
- [ ] Errores 5xx/red → mensaje genérico + reintento; nunca stack trace al usuario.
- [ ] Las listas asumen paginación (no esperan el array completo).

### 5. Rol y permisos (UX, no seguridad)
- [ ] El rol viene de `/me/` (`active_role`), NO hardcodeado.
- [ ] La matriz de permisos del front refleja la del backend (defensa en profundidad), pero el código
      NO asume que el front basta: toda acción sensible la valida el backend.
- [ ] El panel de plataforma solo se muestra si `is_platform_staff` es true (y el backend lo confirma).
- [ ] Rutas protegidas: sin token → redirige a login (no se ve contenido por un instante).

### 6. Configuración de producción
- [ ] `VITE_API_URL` de producción es `https://` (no http).
- [ ] El build de producción no incluye source maps con código sensible (o se sirven restringidos).
- [ ] `npm audit` sin vulnerabilidades altas/críticas en dependencias.
- [ ] CSP configurada en el host/CDN (cabecera Content-Security-Policy).

### 7. Dependencias
- [ ] `npm audit --production` limpio (o vulnerabilidades evaluadas).
- [ ] Sin librerías abandonadas o de fuentes no confiables.
- [ ] Lockfile (`package-lock.json`) versionado y respetado en CI.

## Pruebas manuales recomendadas (con el backend conectado)

1. **Login fallido**: contraseña mala → mensaje claro, sin filtrar si el email existe; el backend
   registra `LOGIN_FAILED` (verificar en `/audit/logs/`).
2. **Token expirado**: esperar a que el access expire (15 min) → la siguiente llamada refresca solo.
3. **Refresh inválido**: borrar el refresh y forzar 401 → redirige a login limpio.
4. **403 por rol**: entrar como `recepcion@vitalis.mx` e intentar (vía la UI o devtools) una acción de
   admin → el backend responde 403 y la UI lo maneja sin romperse.
5. **Aislamiento**: confirmar que no hay forma desde el front de pedir datos de otra clínica (el backend
   da 404; el front nunca debe construir IDs de otro tenant).
6. **Logout**: cerrar sesión → tokens borrados, no se puede volver atrás con el botón del navegador a
   una pantalla con datos.
7. **XSS de prueba**: crear un paciente con nombre `<img src=x onerror=alert(1)>` → debe mostrarse como
   texto, nunca ejecutarse.

## Cómo correr la auditoría

- Usar la skill `react-frontend-connect` (sección "Auditoría de conexiones front↔back").
- Revisión de código: buscar los 10 puntos de la skill (fetch sueltos, rol hardcodeado, tokens en logs,
  dangerouslySetInnerHTML, tipos desincronizados, etc.).
- Herramientas: `npm audit`, ESLint con reglas de seguridad (`eslint-plugin-security` opcional),
  y revisión manual de los flujos de auth.

## Veredicto esperado por fase

- **Antes de conectar datos reales**: pasar categorías 2 (XSS) y 3 (secretos) — son las que abren agujeros.
- **Antes de producción con pacientes reales**: pasar TODO el checklist + migrar tokens a cookie httpOnly
  + HTTPS + CSP + `npm audit` limpio.
