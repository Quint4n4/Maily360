# Reporte de cierre — Fase 4: Permisos por rol y Auditoría

> Fecha: 2026-06-05 · Audiencia: dirección + equipo técnico
> Commits de la fase: `128e283` (/me/), `ffd8c85` (permisos), `50d33dc` (bitácora)

## Resumen ejecutivo

En esta fase el backend pasó de "cualquier usuario logueado puede hacer todo" a un **control de acceso real por rol clínico**, y se sumó una **bitácora de auditoría inmutable** que registra quién accede o modifica cada expediente — requisito directo de NOM-024 y LFPDPPP.

Es la fase que convierte a Maily Soft de "funcional" a "**defendible legalmente**": ahora cada acción sobre datos de salud está restringida por rol y queda registrada de forma inalterable. Junto con el aislamiento multi-tenant y el cifrado ya existentes, el backend tiene los **controles de cumplimiento base** para manejar datos clínicos reales.

## Alcance entregado

| Componente | Qué se construyó | Commit |
|---|---|---|
| **Endpoint `/me/`** | GET /api/v1/me/ devuelve identidad + rol activo + clínica + membresías. El frontend lo usa tras el login para decidir qué panel pintar según el rol. | `128e283` |
| **Permisos por rol** | `apps/core/permissions.py`: clase base `HasClinicRole` (sensible al método HTTP) + 5 políticas declarativas. Aplicado a los 14 endpoints de pacientes/personal/agenda según la matriz aprobada. | `ffd8c85` |
| **Bitácora de auditoría** | `apps/audit`: `AuditLog` append-only tenant-aware, helper `audit_record`, 18 puntos de integración, endpoint de consulta para owner/admin, RLS append-only. | `50d33dc` |

## Cómo se trabajó (flujo de agentes)

Igual que en fases previas: **engineer → tester → reviewer → security → docs**. Cada componente pasó por revisión de código y auditoría de seguridad antes de mergear.

La auditoría de seguridad demostró su valor atrapando **2 problemas críticos para el negocio** que un ojo humano fácilmente habría pasado por alto:

1. **OPTIONS daba 403** → el preflight CORS del navegador habría bloqueado TODA la API desde el frontend. (Corregido: OPTIONS/HEAD no se bloquean por rol.)
2. **Clínicas en prueba quedaban bloqueadas** → como el modelo de negocio es "2 meses gratis", ninguna clínica nueva (estado *trial*) habría podido usar el sistema. (Corregido: trial tiene acceso, suspendido sigue bloqueado.)

Y en la bitácora, la auditoría atrapó una **fuga cross-tenant**: la política de base de datos dejaba que cualquier dueño viera los login fallidos (con emails) de toda la plataforma. (Corregido en migración 0003.)

## Métricas reales

| | |
|---|---|
| Tests al cierre de fase | 594 (~96.7% cobertura) |
| Tests de matriz de permisos | 159 (rol × endpoint × método) |
| Tests de la bitácora | 59 |
| Apps Django totales | 7 (se sumó `audit`) |
| Commits de la fase | 3 de feature + fixes embebidos |

## Hallazgos de seguridad y su resolución

| Componente | Hallazgos | Estado |
|---|---|---|
| Permisos por rol | 2 críticos de negocio (OPTIONS/CORS, trial bloqueado) + refactor de `initial()` + tests de reagendar | ✅ todos corregidos |
| Bitácora | 8 fixes: fuga RLS tenant=NULL, inmutabilidad incompleta (queryset), doble authenticate, fuga de contexto, PII en `resource_repr`, email en claro, paginación sin tope, `_state.adding` | ✅ todos corregidos |
| Higiene | Credencial de prueba filtrada en un commit viejo | ✅ rotada + regla agregada a la skill |

## Cumplimiento (NOM-024 / LFPDPPP)

**Aporta esta fase:**
- **Control de acceso por usuario y rol** al expediente (NOM-024 §5.11).
- **Bitácora de accesos y cambios** inmutable, con conservación de 10 años (NOM-024 §8.1).
- **Minimización de datos**: la bitácora guarda el número de expediente (no nombres), y los login fallidos guardan un hash del email (no el email en claro) — LFPDPPP.
- Registro de **lectura de expediente** (abrir la ficha individual), no solo de escrituras.

**Falta para certificación formal:**
- Exportación de la bitácora (PDF/XLSX firmado) para auditorías de la COFEPRIS.
- Retención automática y particionado (hoy las filas se conservan sin borrado automático).
- Trámite de certificación NOM-024 ante CENETEC + aviso de privacidad LFPDPPP redactado.
- Confirmar que el rol de base de datos en producción no sea superuser (para que el REVOKE de la bitácora aplique).

## Pendientes anotados

- **X-Tenant-ID**: usuarios con membresía en varias clínicas hoy resuelven siempre la más antigua; falta el mecanismo de elección explícita de clínica.
- **Role enforcement en el frontend**: el backend ya devuelve 403; el frontend debe manejarlo (ocultar acciones no permitidas + manejar el error).
- **Bitácora v2**: exportación, retención automática, particionado.
- **PATIENT_LIST**: por decisión del dueño se audita solo el detalle del expediente, no los listados; reconsiderar antes de la certificación formal.

## Próximo paso recomendado

Con cimientos, operación clínica (agenda), control de acceso y trazabilidad listos, las opciones naturales son: (a) **apoyar el frontend** para tener el primer panel demo-able de punta a punta, (b) construir el **expediente clínico** (el corazón clínico), o (c) el **panel de plataforma** (la vista de dueño SaaS con métricas y billing).
