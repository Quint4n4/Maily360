# Plan de implementación — Sucursales (multi-sede) por negocio

> Complementa a [`sucursales-arquitectura-analisis.md`](./sucursales-arquitectura-analisis.md).
> Enfoque decidido: **Opción A** (sucursal DENTRO del tenant). Estado: **plan aprobado
> para construir por fases**. Autor: 2026-07-10.

## Principios (aplican a TODAS las fases)

1. **Compatibilidad hacia atrás:** todos los FK `sucursal` nacen **nullable** y hay una
   **"Sucursal Principal"** por negocio. Una clínica de una sola sede **no nota ningún
   cambio**.
2. **RLS no se toca:** la barrera de seguridad sigue siendo `tenant_id`. La sucursal es un
   **filtro operativo + validación en la capa de servicio/permiso**, no una política RLS.
   Toda tabla nueva es `TenantAwareModel` con su RLS por tenant (el test guardián lo exige).
3. **La sucursal activa** viaja por request (header `X-Sucursal-Id`), se valida contra las
   sedes permitidas del usuario (`MembershipSucursal`); el dueño puede todas. NO usa el GUC
   de RLS.
4. **Local-first:** cada fase se construye local, se prueba (backend + front verdes + PDF/E2E
   donde aplique) y se revisa (seguridad + code review) antes de subir. Se sube por fases,
   no de un jalón.
5. Regla de negocio guía: **paciente + su info (clínica y su cuenta) = del NEGOCIO
   (compartido). Operación y dinero DE la sede = de la sede. El dueño ve todo.**

---

## Fase 0 — Decisiones finales (sin código)

Confirmar antes de arrancar:
- **Catálogos y precios (servicios, paquetes, analitos, plantillas):** ¿iguales para todo
  el negocio (recomendado) o distintos por sede? → Recomendado: **compartidos ahora**;
  "precio/override por sede" queda como mejora futura (no bloquea).
- **Membrete/dirección en PDFs:** ¿el del negocio (ahora) o el de la sede donde se atiende?
  → Recomendado: negocio ahora, **por sede en Fase 4**.
- **`AppointmentType` (tipos/colores) y `TenantAgendaConfig` (recordatorios):** compartidos
  (recomendado) u override por sede (futuro).
- **Facturación del SaaS:** se cobra por **negocio** (recomendado), no por sucursal.

---

## Fase 1 — Base multi-sede (fundamento)

**Meta:** existe la Sucursal, el usuario tiene sedes asignadas, hay selector de sucursal, y
**personal + consultorios** se ven por sede.

### Backend
- **Modelo `Sucursal(TenantAwareModel)`** en `apps/clinica` (o nueva `apps/sucursales`):
  `name`, `address`, `phone`, `timezone` (opc), `color_hex` (opc para agenda), `is_active`,
  `is_default`. Constraint: una sola `is_default=True` por tenant. Migración de esquema +
  **migración RLS** (USING+WITH CHECK, patrón de siempre).
- **Modelo `MembershipSucursal(TenantAwareModel)`**: `membership` FK, `sucursal` FK
  (qué usuario opera en qué sede). RLS.
- **`Consultorio.sucursal`** (FK nullable) y **`Doctor.sucursales`** (M2M). Migraciones
  (solo AddField).
- **Data migration (backfill):** por cada tenant → crear "Sucursal Principal"
  (`is_default=True`); asignar todos los consultorios y doctores existentes a ella; crear
  `MembershipSucursal` de cada membresía a la principal. Owner/admin: acceso a todas
  (implícito por rol, no hace falta fila por sede).
- **Resolución de sucursal activa:** helper `current_sucursal(request)` +
  `allowed_sucursales(user, tenant)` (owner → todas; resto → sus `MembershipSucursal`). Un
  permiso/mixin valida que la sucursal activa esté permitida (si no → 403). Vive en
  `apps/core` junto al contexto de tenant, pero **sin GUC**.
- **CRUD `Sucursal`:** `GET/POST /api/v1/clinica/sucursales/`, `GET/PATCH/DELETE .../<id>/`
  (escritura owner/admin; lectura owner/admin/doctor…). Selectors + services + serializers.
- **`/me` extendido:** devuelve `sucursales` (las permitidas del usuario) + `sucursal_default`.
- **Scoping:** `consultorio_list` y `doctor_list` filtran por la sucursal activa.

### Frontend
- **Selector de sucursal** en el `Topbar` (junto al usuario). Guarda la sucursal activa
  (contexto tipo `SucursalContext`); manda `X-Sucursal-Id` en el cliente http. Si el usuario
  tiene una sola sede → oculto/automático.
- **Gestión de Sucursales** en Mi Consultorio ("Sucursales", owner/admin): crear/editar/
  desactivar.
- En **Personal** y en el editor de **Consultorios**: asignar `consultorio → sucursal` y
  `doctor → sucursales`; las listas se filtran por la sucursal activa.

### Tests
Modelo + RLS de las 2 tablas nuevas (guardián verde); CRUD/permisos; backfill idempotente;
`/me` trae sucursales; filtros de consultorios/doctores por sede; validación de sucursal no
permitida → 403.

### Criterio de aceptación
Una clínica existente queda con todo bajo "Sucursal Principal" (sin cambios visibles). Se
puede crear una 2ª sede y mover/asignar consultorios y doctores; el selector cambia el
contexto de personal/consultorios.

---

## Fase 2 — Agenda por sucursal

**Meta:** cada sede tiene su agenda independiente; la disponibilidad se calcula por sede.

### Backend
- **`Appointment.sucursal`**, **`AgendaBlock.sucursal`**, **`DoctorSchedule.sucursal`**
  (FK nullable). Backfill: derivar de `consultorio.sucursal` (o principal).
- `appointment_create`/`reschedule`: setear/validar `sucursal` (del consultorio o explícita)
  y que el actor tenga acceso a esa sede. El **anti-empalme** sigue por doctor/consultorio
  (ya cubre la sede). El endpoint de **disponibilidad** filtra por sucursal.
- Listado/calendario de agenda filtrado por la sucursal activa.

### Frontend
- La página de **Agenda** filtra por la sucursal activa; `CrearEventoModal` ofrece solo los
  doctores/consultorios de esa sede; la disponibilidad en vivo se calcula por sede. Horario
  laboral del médico configurable por sede.

### Tests
Scoping de agenda; un rol acotado (recepción de Centro) no ve/crea citas de Norte; anti-
empalme y disponibilidad por sede; backfill.

### Criterio de aceptación
La recepción de Centro solo ve y agenda en Centro; el dueño cambia de sede con el selector.

---

## Fase 3 — Finanzas por sucursal (cuenta compartida / caja privada)

**Meta:** el estado de cuenta del paciente se comparte; los reportes/caja de cada sede son
privados.

### Backend
- **`Charge.sucursal`, `Payment.sucursal`, `Quote.sucursal`** (dónde se generó; FK nullable,
  backfill a principal). `PaymentAllocation`/`CfdiDocument` heredan vía el cargo.
- `charge_create`/`payment`/`quote_create`: `sucursal = sucursal activa`; validar acceso.
- **Estado de cuenta del paciente:** agrega TODOS sus cargos/pagos **sin filtrar por sede**
  (compartido); columna informativa de "sede".
- **Reportes de finanzas por sede (PRIVADOS):** dashboard, reportes, **cierre diario**, RFM,
  antigüedad → **filtran por la sucursal activa**. Un admin/finanzas de sede ve solo su sede;
  el **dueño** ve consolidado + selector por sede. Permisos: acotar por `MembershipSucursal`.

### Frontend
- **Finanzas:** dashboard/reportes/cierre filtran por la sucursal activa según el alcance del
  usuario; el dueño tiene "todas / por sede"; el admin de sede queda fijo en su sede. El
  **estado de cuenta del paciente** sigue mostrando todo (con la columna de sede).

### Tests
El cargo lleva sucursal; el estado de cuenta del paciente = todas las sedes; el dashboard se
filtra; el admin de Centro NO ve ingresos de Norte; el dueño ve consolidado. **Caso
Acapulco→CDMX** cubierto por test.

### Criterio de aceptación
Paciente de Acapulco cobrado en CDMX: el cobro aparece en su cuenta (visible en ambas) y
cuenta para la caja de CDMX; el admin de CDMX no ve la caja de Acapulco.

---

## Fase 4 — Operación fina / overrides por sede

- **Gestión de `MembershipSucursal`** (UI): asignar usuarios a sedes y definir "admin de
  sucursal".
- **Overrides por sede (opcionales):** membrete/dirección en PDFs de la sede donde se
  atiende; `ClinicTeamMember` (equipo del Plan Integral) por sede; `AppointmentType`/
  `TenantAgendaConfig` por sede.
- **Auditoría filtrable por sede** para el admin de sede.
- (Opcional) precio por sede en catálogos.

---

## Fase 5 (opcional) — Muralla dura entre sedes

Solo si el negocio lo exige: agregar `sucursal_id` a las políticas RLS (segunda dimensión de
GUC) o migrar a Opción B. Alto costo; hoy **no** requerido (lo único privado pedido —
finanzas por sede— se cubre con scoping en Fase 3).

---

## Riesgos y mitigaciones

- **Amplitud del cambio** (agenda y finanzas tocan muchos endpoints): centralizar la
  resolución de sucursal activa + un helper para filtrar querysets, y avanzar por fases con
  pruebas entre cada una.
- **Complejidad de alcance por rol:** dejar MUY claro quién es de-negocio (dueño / admin de
  todas las sedes) vs acotado-a-sede; cubrir con tests de permisos por sede.
- **La sucursal NO es barrera RLS:** documentado; la privacidad de finanzas por sede se
  enforcea en servicio/permiso (aceptado por el dueño). Si algún día se quiere muralla dura
  → Fase 5.
- **Relación con el "selector de clínica" pendiente** (usuarios en varios negocios): son
  niveles distintos (negocio vs sede). El selector de sucursal es un hermano, no lo mismo.

## Orden recomendado

Fase 1 → 2 → 3 (aquí ya está el 90% del valor y tu caso de uso resuelto) → 4 → (5 si se
necesita). Cada fase es entregable y probable por separado.
</content>
