# Plan — Paneles por rol (maily360)

> Objetivo: construir las distintas **vistas por rol** del sistema, con **login real**
> (cada usuario entra con su cuenta y la app carga la vista de su rol).
> Alcance: **ambos frontends** — la app de la clínica (`web-soft`) y el panel interno de
> Maily (`web-platform`).
> Estilo: el mismo **glass dorado** que ya tenemos.

---

## 0. Los dos mundos del sistema

Tu backend separa a los usuarios en dos grupos (campo `is_platform_staff` en `authn`):

| Mundo | Frontend | Quién entra | Roles |
|---|---|---|---|
| **Clínica** | `web-soft` (lo que ya construimos) | Personal de cada clínica | owner, admin, doctor, nurse, reception, finance, readonly |
| **Plataforma Maily** | `web-platform` (nuevo) | Tu equipo interno | super_admin, sales, engineering |

**Login real:** al iniciar sesión, el backend dice si el usuario es `is_platform_staff`.
- Si **sí** → entra al **panel de plataforma**.
- Si **no** → entra a la **app de la clínica**, y la UI se adapta a su rol de `TenantMembership`.

---

## Matriz de permisos — App de la clínica

Qué módulo ve/edita cada rol (✅ editar · 👁 solo ver · 🚫 no ve):

| Módulo | owner / admin | doctor | nurse | reception | finance | readonly |
|---|---|---|---|---|---|---|
| Agenda | ✅ | ✅ | ✅ | ✅ | 👁 | 👁 |
| Contactos (datos) | ✅ | ✅ | 👁 | ✅ | 👁 | 👁 |
| Expediente clínico | ✅ | ✅ | 👁/parcial | 🚫 | 🚫 | 👁 |
| Personal (doctores/consultorios) | ✅ | 🚫 | 🚫 | 🚫 | 🚫 | 🚫 |
| Configuración de agenda | ✅ | su propia¹ | 🚫 | 🚫 | 🚫 | 🚫 |
| Finanzas | ✅ | 🚫 | 🚫 | 🚫 | ✅ | 👁 |

¹ El doctor configura **su** duración de cita desde su ficha (ya lo hicimos), pero no la
configuración global de la clínica.

> Regla transversal: **readonly** ve todo pero sin botones de crear/editar/eliminar.

---

## Matriz de permisos — Panel de plataforma (Maily)

| Pantalla | super_admin | sales | engineering |
|---|---|---|---|
| Dashboard de plataforma (métricas) | ✅ | ✅ | ✅ |
| Clínicas / tenants (lista + alta + suspender) | ✅ | ✅ | 👁 |
| Suscripciones / planes | ✅ | ✅ | 🚫 |
| Usuarios de plataforma (equipo Maily) | ✅ | 🚫 | 🚫 |
| Salud del sistema / logs | ✅ | 🚫 | ✅ |

---

## Fases de construcción (orden recomendado)

### ▸ Fase 0 — Cimientos de autenticación y roles  *(base técnica, sin esto nada se adapta)*
1. **AuthContext** (`src/auth/`): guarda el usuario actual `{ nombre, email, isPlatformStaff, role }` y funciones `login/logout`.
2. **Tipos de rol**: `ClinicRole` y `PlatformRole` (los 7 + 3 del backend).
3. **Mapa de permisos** (`src/auth/permisos.ts`): un objeto central que diga qué módulos ve cada rol → de aquí salen el menú y las rutas.
4. **Login real (demo)**: cuentas demo, una por rol; al entrar, setea el usuario en el context y redirige al mundo correcto.
5. **Rutas protegidas**: `<RequireAuth>` y `<RequireRole>` (si tu rol no tiene acceso → te manda a tu inicio).
6. **Logout** real (limpia sesión, vuelve al login).

*Tamaño: mediano. Es la pieza clave — todo lo demás se apoya aquí.*

### ▸ Fase 1 — App de clínica adaptada por rol  *(lo más visible para la demo)*
1. **Navbar dinámico**: el Topbar muestra solo los módulos del rol (según el mapa de permisos).
2. **Modo solo-lectura**: ocultar botones de acción cuando el rol es `readonly` (o `👁`).
3. **Recepción vs clínico**: en Contactos, recepción ve datos básicos pero NO el expediente clínico.
4. **Finanzas** (nuevo módulo): pantalla para `finance`/admin — cuentas por cobrar, ingresos del día/mes, pagos. *(No está en el backend aún; sería visual + se define después.)*
5. Probar cada rol con su cuenta demo.

*Tamaño: mediano-grande (Finanzas es lo más nuevo).*

### ▸ Fase 2 — Panel de plataforma de Maily (`web-platform`)
1. **Scaffolding** del segundo frontend (mismo stack: Vite + React + TS + Tailwind glass).
2. **Login + roles de plataforma** (reusar el AuthContext).
3. **Pantallas**:
   - Dashboard (métricas: nº de clínicas, activas, en prueba, ingresos).
   - **Clínicas/tenants**: lista con estado (Trial/Activa/Suspendida), detalle, alta, suspender/activar.
   - **Suscripciones/planes** (sales + super_admin).
   - **Usuarios de plataforma** (solo super_admin).
   - **Salud del sistema** (engineering).
4. Adaptar por rol (super_admin / sales / engineering).

*Tamaño: grande (es casi otra app).*

### ▸ Fase 3 — Pulido y preparación de la demo
1. **Cuentas demo** documentadas (un usuario por rol, clínica y plataforma).
2. Consistencia visual (glass dorado en ambos frontends).
3. **Guion de demo**: orden para enseñar cada rol al cliente.

---

## Decisiones técnicas ya tomadas
- **Login real por rol** (no selector): el rol viene del usuario; la UI se arma sola.
- **Permisos centralizados** en un solo archivo (`permisos.ts`) — fácil de ajustar.
- **Demo sin backend**: cuentas demo simulan los roles hasta conectar la API real.

## Qué falta decidir más adelante
- ¿`web-platform` es un proyecto separado o una ruta dentro del mismo? (Recomendado: proyecto
  separado, como ya está estructurado el monorepo).
- Alcance real de **Finanzas** (no está en el backend) — definir con el cliente.

---

## Punto de partida sugerido
Empezar por **Fase 0** (cimientos de auth + permisos). Es invisible pero es lo que permite
que todo lo demás se adapte por rol. En cuanto esté, la Fase 1 (clínica por rol) avanza rápido
porque ya tenemos casi todas las pantallas.
</content>
