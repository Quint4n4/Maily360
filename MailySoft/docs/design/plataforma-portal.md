# Portal de Plataforma (panel interno de Maily)

> Construido durante el sprint de **2026-06-16**.
> Estado: **FUNCIONAL** (login → panel → datos reales → alta/ficha de clínica). Backend con tests verdes; frontend compila. **SIN COMMITEAR** (sesión paralela del expediente toca el mismo repo).
> Backend: app nueva `apps/plataforma` (+ permisos en `apps/core/permissions.py`). Frontend: `web-soft/src/pages/plataforma/`, `src/platform/`, `src/components/plataforma/`.

---

## 1. Objetivo

Un portal separado del de la clínica para que el **equipo interno de Maily** opere el negocio: ver todas las clínicas, darlas de alta, suspenderlas, y administrar al equipo. Es **cross-tenant** (ve TODAS las clínicas), a diferencia del portal de clínica (que solo ve la suya).

---

## 2. Roles y modelo (locked)

- **D-A · Dos niveles.** Plataforma (Maily como empresa) vs Clínica (cada cliente). Un usuario puede ser **ambos** (p. ej. `admin@maily.local` es super_admin de Maily Y owner de una clínica demo).
- **D-B · 3 roles de plataforma** (`User.platform_role`, solo si `is_platform_staff=True`): `super_admin` (Súper Admin / dueño de Maily), `sales` (Ventas), `engineering` (Ingeniería). Se decidió **dejar estos 3** (no se agregó un rol "finanzas"; lo cubre super_admin).
- **D-C · Matriz de acceso**: métricas y lista de clínicas → los 3; **alta/suspender clínica** → super_admin + sales; **usuarios de plataforma** → solo super_admin.
- **D-D · El backend es la autoridad.** El front tiene un selector "Ver como (demo)", pero los permisos reales los impone el backend por `platform_role`.

---

## 3. Seguridad cross-tenant (el corazón)

- Las vistas heredan de **`PlatformAPIView`** (NO de `TenantAPIView`): no resuelven membresía ni setean el GUC `app.current_tenant_id`. El `TenantMiddleware` deja el GUC en `''` → `current_tenant_id()` = NULL → la policy RLS `(... OR current_tenant_id() IS NULL)` **abre todas las filas**. Los selectors usan `Model.all_objects` (nunca `.objects`, que devolvería `qs.none()` sin tenant).
- Permisos: `IsPlatformStaff` (puerta de entrada) + subclases por módulo (`PlatformMetricsPermission`, `PlatformClinicReadPermission`, `PlatformClinicWritePermission`, `PlatformStaffListPermission`).
- **Auditado dos veces** (django-security). Veredicto: sin críticos/altos tras los fixes. Ninguna vista de clínica hereda de `PlatformAPIView`.

---

## 4. Endpoints (`api/v1/plataforma/`)

| Método | Ruta | Qué hace | Permiso |
|---|---|---|---|
| GET | `/metricas/` | Conteos del dashboard | los 3 roles |
| GET | `/clinicas/` | Lista de clínicas (+ conteos) | los 3 roles |
| **POST** | `/clinicas/` | **Alta de clínica nueva + dueño** | super_admin, sales |
| GET | `/clinicas/<id>/` | **Ficha** de una clínica | los 3 roles |
| POST | `/clinicas/<id>/estado/` | Suspender / reactivar | super_admin, sales |
| GET | `/usuarios/` | Equipo interno de Maily | solo super_admin |

---

## 5. Alta de clínica (lo más privilegiado)

`tenant_and_owner_create(*, actor, name, owner_email, owner_first_name, owner_last_name, timezone="America/Mexico_City", trial_days=60)`:
- Genera **slug único** (slugify + sufijo) y una **contraseña temporal** con `secrets` (16 chars, sin caracteres ambiguos, ~96 bits).
- En **una transacción atómica**: crea Tenant (estado `trial`, fin a `trial_days`), reusa `member_create` para el **dueño** (rol owner), y **datos semilla** (1 consultorio + 3 tipos de cita) para que la clínica nazca lista para agendar. Audita `TENANT_CREATE`.
- ⚠️ La contraseña temporal **solo** se devuelve en la respuesta del POST (para mostrarla una vez); **nunca** se persiste, audita ni loguea. La respuesta lleva `Cache-Control: no-store`.
- Defensa en profundidad: el service revalida `is_platform_staff` + rol del actor.

**Ficha** (`platform_clinica_detail`): datos + conteos reales (usuarios/pacientes/citas) + última actividad + lista de miembros (sin PII sensible ni hashes).

---

## 6. Frontend

- **Login** (`destinoTrasLogin`): si eres staff de Maily, entras al **panel de plataforma**; si además tienes clínica, saltas con el switcher.
- **Switcher entre portales**: en el topbar de plataforma → "Ir a mi clínica"; en el topbar de clínica → "Panel de Maily". (Se arregló también que el logout del panel de plataforma sí cierra sesión de verdad.)
- **Rol real**: `PlatformRoleProvider` toma el `platform_role` real de `/me/` (el "Ver como" solo previsualiza).
- **Páginas reales**: Dashboard (conteos), Clínicas (lista + alta + ficha + suspender/reactivar), Usuarios (equipo). Componentes nuevos: `NuevaClinicaModal` (form + contraseña temporal con copiar), `ClinicaDetailDrawer` (ficha).
- **Maqueta aún**: Suscripciones (necesita facturación) y Sistema (necesita monitoreo de infra).
- Guardas: `/plataforma/*` exige sesión (`RequireAuth`) + `is_platform_staff` real.

---

## 7. Auditoría de seguridad — fixes aplicados

- **ALTO-1**: carrera de slug → se captura `IntegrityError` y se responde 400.
- **MEDIO-1**: `Cache-Control: no-store` en la respuesta con la contraseña.
- **MEDIO-2**: validación IANA de `timezone`.
- **BAJO-1/2**: nombre debe dar slug útil; email del dueño fuera de la metadata de auditoría.

### Pendiente de seguridad (diferido)
- **MEDIO-3**: forzar **cambio de contraseña en el primer login** del dueño (`must_change_password`). Requiere un flujo de cambio de contraseña que aún no existe. Mitigación operativa actual: el agente relata la temporal y pide cambiarla.
- **X-Forwarded-For** para la IP de auditoría: patrón de todo el proyecto; se resuelve con config de proxy en producción.

---

## 8. Pendientes / siguientes áreas del panel
- **Suscripciones y facturación** (planes, MRR real, pasarela de pago + CFDI).
- **Sistema** real (ping a BD/Redis/Celery, métricas de WhatsApp).
- **Usuarios**: invitar/crear staff de Maily, reset password, y búsqueda de usuarios de clínicas para soporte.
- **Clínicas**: editar datos, cambiar plan, extender prueba, "entrar como" (impersonar con bitácora).
- **Bitácora cross-tenant** consultable (la auditoría NOM-024 ya existe en el backend).
- Setup: `admin@maily.local` necesita `platform_role` asignado para usar el panel (se hace en BD/Django admin).
