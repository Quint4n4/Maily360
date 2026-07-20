# Mapa multi-sede por app (auditoría por APP)

> 2026-07-16. Barrido de TODAS las apps del backend para verificar cuáles conocen las
> sucursales y cuáles no. Nace de la lección de los clústers F (`tenancy`) y G (`notas`):
> las auditorías previas revisaron POR FEATURE y esas dos apps se escaparon por no importar
> `apps.clinica.sucursal_scope`. Aquí la regla es: **una app entra al barrido aunque no sepa
> que las sedes existen.**

Señal rápida usada: ¿importa `sucursal_scope`? ¿su modelo tiene campo `sucursal`? ¿qué datos posee?

## A) Correctamente sede-aware (auditadas a fondo — VERDE)

| App | Qué es privado por sede | Estado |
|---|---|---|
| `clinica` | Núcleo del modelo: `Sucursal` + `MembershipSucursal` + `sucursal_scope.py` | ✅ RLS propia correcta |
| `agenda` | Citas, bloqueos/eventos, horarios | ✅ clústers A1–A4 cerrados |
| `personal` | Consultorios, asignación médico↔sede/consultorio | ✅ A4/A5/C + F3 |
| `finanzas` | Caja, cierre, dashboard, reportes, CFDI (el estado de cuenta del paciente es COMPARTIDO a propósito) | ✅ A6/A7/D + F1/F2 |
| `tenancy` | Miembros (Equipo) por sede + jerarquía de roles | ✅ clúster F + F' |
| `notas` | Avisos por sede + importante del dueño | ✅ clúster G |

## B) Sede-aware donde aplica; el resto compartido por diseño (VERDE)

| App | Parte sede-aware | Parte compartida |
|---|---|---|
| `expediente` | Calendarización de sesiones (toca agenda/sede) — clúster A8 | El EXPEDIENTE clínico (HC, evolución, dx, alergias, signos) es compartido entre sedes |
| `authn` | Expone las sedes permitidas del usuario en `/me/` (inicializa el selector del front) | — |

## C) Compartidas por diseño — NO necesitan sede (VERDE)

| App | Por qué no lleva sede |
|---|---|
| `pacientes` | El paciente es COMPARTIDO entre sedes (decisión de negocio) |
| `recetas` | Parte del expediente clínico compartido |
| `pdfs` | Infra: los jobs reciben el alcance de sede de quien los crea (finanzas ya congela `sucursal_ids`) |
| `core` | Infra base (`TenantAwareModel`, contexto de tenant, permisos) |
| `plataforma` | Cross-tenant, por ENCIMA de las sedes. (Aquí vivirá el aviso de mantenimiento — "tipo 3" — PENDIENTE) |

## D) GAPS encontrados — ✅ CERRADOS 2026-07-16 (decisiones del dueño)

> **audit → bitácora solo para el dueño; notificaciones → campana filtrada por sede.**
> - `audit`: `AuditLogPermission` ahora exige `owner` (antes owner+admin). Un admin recibe 403.
>   Tests actualizados en `apps/audit/tests/test_apis.py` (admin→403; `admin` movido a FORBIDDEN_ROLES).
> - `notificaciones`: helper compartido `filter_recipients_by_sucursal` en
>   `apps/notificaciones/recipients.py` (movido desde notas). Aplicado en los fanouts AMPLIOS por rol,
>   dejando SIEMPRE a los directamente involucrados (médico de la cita, quienes ya comentaron):
>   `agenda/notes.py` (recepción → sede de la cita), `agenda/blocks.py` (clinic_staff → sede del
>   evento), `expediente/services.py` (enfermería → sede de la cita de la evolución). `notas` ya lo
>   usaba. `clinica/services.py` (credencial fiscal → owners+admins) se DEJA: recurso nivel-tenant.
>   Tests: `apps/notificaciones/tests/test_filter_sucursal.py`. Verificado: apps afectadas 1308 passed.
>
> **REFINAMIENTO (2026-07-16, feedback del dueño): el DUEÑO queda FUERA de la campana de una sede
> específica.** El owner "puede ver" todas las sedes, así que el filtro basado en `allowed_sucursales`
> lo incluía → le sonaba la campana de cada aviso interno de cada sucursal (lo reportó el dueño). Ahora
> `filter_recipients_by_sucursal` EXCLUYE a los owners cuando `sucursal_id != None`: un aviso *de
> sucursal* suena solo a los MIEMBROS de esa sede. El dueño lo sigue VIENDO en la lista de Notas
> (supervisión), pero no lo pingamos. Un aviso a "todas las sedes" (sucursal_id=None) sí le llega a
> todos, incluido el dueño.

### 🟠 `audit` — MEDIO (exposición de info entre sedes) — RESUELTO (owner-only)
La bitácora (`AuditLogListApi`, gated a owner+admin) **NO se acota por sede**: `audit_log_list`
no recibe filtro de sucursal. Un **admin de sucursal ve quién hizo qué en TODAS las sedes**
(cargos, cancelaciones, altas, pacientes de otras sedes). El modelo `AuditRecord` **no tiene
campo `sucursal`** (los refs a "sucursal" son solo tipos de acción, p.ej. `SUCURSAL_CREATE`).
- Solo lectura, gated a owner+admin, pero inconsistente con el modelo de "admin de sucursal ve
  solo lo suyo".
- **Arreglo (necesita decisión):** (a) restringir la bitácora a **solo dueño**; o (b) añadir
  `sucursal` a los registros de auditoría + backfill + acotar el listado por `sucursal_scope_ids`.

### 🔵 `notificaciones` — BAJO (ruido de campana entre sedes, NO fuga de datos)
Varios `notification_fanout` reparten a TODO el tenant en eventos PRIVADOS de una sede:
- `agenda/notes.py`: nota en una cita de Norte → notifica a `users_with_role(RECEPTION)` = recepción
  de TODAS las sedes (incluida Centro).
- `agenda/blocks.py`: un bloqueo/evento sin médico → `clinic_staff_users(tenant)` = todo el staff.
- `expediente/services.py`: indicación a `users_with_role(NURSE)` = enfermería de todo el tenant.
- (`clinica/services.py` notifica a owners+admins por un tema fiscal = nivel-tenant, aceptable.)

Es **ruido** (el contenido es un título corto; al abrir la notificación, el recurso ya está
acotado por sede → 404 si es de otra sede), no exposición de datos sensibles. El fanout de `notas`
YA se arregló (`_filter_recipients_by_sucursal`); falta aplicar el MISMO filtro a los demás
(agenda notas/bloqueos, expediente enfermería).

## Veredicto del mapa
El **núcleo operativo** (agenda, finanzas, personal, tenancy, notas, clinica) está correctamente
acotado por sede y verificado. Lo compartido (paciente, expediente, recetas, catálogos) es
compartido **a propósito**. Quedan **2 apps por decidir**: `audit` (medio) y `notificaciones`
(bajo), más la feature nueva **tipo 3** (aviso de mantenimiento de plataforma). Ninguno bloquea
las pruebas actuales del dueño.
