# Análisis de arquitectura — Sucursales por negocio (multi-sede)

> Estado: **ANÁLISIS / propuesta**. No hay código aún. Objetivo: decidir el enfoque
> antes de tocar nada. Autor: sesión 2026-07-10.

## 1. Problema

Hoy un **negocio = un `Tenant`** (una clínica). Se quiere que **un mismo negocio tenga
varias SUCURSALES** (sedes/ubicaciones), cada una con su propio personal, agenda,
consultorios y (a futuro) especialidades e inventario, pero compartiendo lo que tenga
sentido compartir (pacientes, catálogos, marca) y con **reportes consolidados** para el
dueño.

## 2. Estado actual (lo que hay)

- **`Tenant`** (`apps/tenancy/models.py`): la clínica. Raíz del aislamiento.
- **Aislamiento multi-tenant de UNA dimensión**: `TenantAwareModel.tenant` + **RLS de
  PostgreSQL** filtrando por `tenant_id` (GUC `app.current_tenant_id`, fijado por request).
  Es una barrera de seguridad dura y probada (test guardián de cobertura RLS).
- **`TenantMembership`**: usuario + tenant + rol. **No tiene dimensión de sucursal.**
- **`Consultorio`** (`apps/personal`): un cuarto/sala. Su `location` es **texto libre**
  ("piso, ala"), no una entidad. NO es una sucursal.
- **`Doctor`**: M2M a `consultorios`; `specialty` es texto libre.
- **`Appointment`**: FK a `patient`, `doctor`, `consultorio`.
- **`Patient`, catálogos** (`ServiceConcept`, `LabAnalyte`, `DocumentTemplate`,
  `TreatmentPackage`, equipo, preguntas de HC): todos a nivel **tenant** (compartidos).
- **No existe** ninguna noción de sucursal (solo un bullet de marketing "Multi-sucursal"
  en el plan Premium, sin respaldo técnico).

**Conclusión:** para varias sucursales HOY habría que crear **varios tenants
separados**, sin empresa madre que los agrupe, sin pacientes/catálogos compartidos y sin
reportes consolidados. Eso NO es lo que se quiere.

## 3. Las tres opciones de diseño

### Opción A — Sucursal COMO ENTIDAD DENTRO del tenant  ⭐ recomendada
`Tenant (negocio)` → muchas `Sucursal`. La sucursal es una **segunda dimensión de
scoping** (operativa), no un nuevo tenant.

- El aislamiento de seguridad sigue siendo **por tenant** (RLS sin cambios).
- Se agrega un FK **opcional** `sucursal` a las tablas que lo necesiten
  (consultorio, cita, horario, cargo…). La sucursal **filtra** las vistas; no es una
  barrera de seguridad dura entre sedes del mismo negocio.
- Pacientes y catálogos quedan **a nivel tenant** (compartidos por todas las sucursales).
- El dueño ve todo; se puede filtrar por sucursal o consolidar.

**Pros:** reutiliza el multi-tenant existente sin tocar RLS; pacientes y catálogos
compartidos (continuidad de atención entre sedes); reportes consolidados triviales;
migración incremental (FK nullable + sucursal por defecto). **Encaja con "un negocio con
varias sucursales".**
**Contras:** las sucursales del mismo negocio **no quedan aisladas por seguridad dura**
entre sí (un usuario con acceso al tenant podría, a nivel BD, ver otras sedes; el filtro
por sucursal es operativo/UX + validación en capa de servicio, no RLS). Si se exige
muralla entre sedes, hay que reforzar (ver Fase 4 / Opción B).

### Opción B — Cada sucursal ES un Tenant, agrupadas por una "Organización"
`Organización (empresa)` → muchos `Tenant (sucursal)`.

- Cada sucursal queda **aislada por RLS** (muralla dura entre sedes).
- Se agrega una capa `Organización` para agrupar tenants y dar administración/reportes
  cross-sede al dueño.

**Pros:** aislamiento máximo entre sedes (bueno si son casi negocios independientes o hay
requisito legal de separación). Reusa RLS tal cual.
**Contras:** **pacientes y catálogos NO se comparten** (viven por tenant) → un paciente
que va a dos sedes tendría dos expedientes; los catálogos se duplican. Reportes
consolidados y "buscar paciente en toda la empresa" se vuelven **cross-tenant** (complejo,
va contra el diseño RLS actual). El login multi-sede y los permisos se complican. Mucho
más trabajo para lo que el negocio realmente pide.

### Opción C — Híbrida
Tenant = negocio (como A), pero se le mete a la Sucursal una **frontera de servicio**
fuerte: cada consulta/servicio valida en la capa de negocio que el actor pertenezca a esa
sucursal, y (opcional, Fase 4) se añade `sucursal_id` a las políticas RLS para muralla
dura. Es "A con endurecimiento gradual".

## 0. Decisiones tomadas (2026-07-10, con el dueño)

- **Enfoque: Opción A** (sucursal dentro del negocio/tenant).
- **Se COMPARTE entre sucursales (nivel negocio):** pacientes, expediente/historial
  clínico completo, y el **estado de cuenta del paciente** (sus cargos/pagos/adeudo).
  → Ejemplo confirmado: paciente registrado en Acapulco que va a CDMX; en CDMX se ve su
  expediente Y su información financiera (su cuenta) igual que en Acapulco.
- **Es INDEPENDIENTE por sucursal:** **personal**, **consultorios** y **agenda**.
- **Finanzas — matiz clave:** el **estado de cuenta del PACIENTE** se comparte (sigue al
  paciente), PERO **los reportes/caja/ingresos de cada SEDE son privados de esa sede**
  (una sede no ve la caja ni los reportes de ingresos de otra; el dueño/admin sí ve todo,
  consolidado y por sede). No es muralla dura de base de datos (mismo tenant): es scoping
  por sucursal en la capa de servicio + por rol.
- **Aislamiento:** NO se requiere muralla RLS entre sedes; basta el filtro por sucursal +
  validación en backend. (La única "privacidad" pedida es la de los reportes financieros
  por sede, que se resuelve con scoping, no con RLS.)

## 4. Recomendación

**Opción A** (sucursal dentro del tenant), con la puerta abierta a endurecer (C/Fase 4)
si algún día se necesita muralla dura entre sedes.

Razón: lo que se pide es **un negocio con varias sucursales**, compartiendo pacientes,
catálogos y marca, con reportes consolidados. Eso es exactamente el punto fuerte de A y el
punto débil de B. B solo gana si las sucursales fueran casi empresas separadas — no es el
caso.

## 5. Modelo de datos propuesto (Opción A)

Nueva entidad:

```
Sucursal(TenantAwareModel)
  name            CharField        # "Sucursal Centro", "Sucursal Norte"
  address, phone  ...
  timezone        # opcional, por si hay sedes en zonas distintas
  is_active       Bool
  is_default      Bool            # una por tenant, la que se elige por defecto
```

FK **opcional** `sucursal` (nullable, para migrar sin romper) en las tablas operativas:

| Modelo | ¿Lleva `sucursal`? | Nota |
|---|---|---|
| `Consultorio` | **Sí** | un cuarto pertenece a una sede |
| `Doctor` | **M2M** `sucursales` | un médico puede atender en varias sedes |
| `DoctorSchedule` | **Sí** | el horario laboral es por sede |
| `Appointment` | **Sí** | agenda independiente por sede |
| `Charge`/`Payment` (finanzas) | **Sí** (dónde se generó) | **doble naturaleza**: el cargo pertenece al `patient` (aparece en su estado de cuenta en CUALQUIER sede) **y** lleva `sucursal` (dónde se cobró → cuenta para los ingresos/caja de ESA sede). El **estado de cuenta del paciente** = todos sus cargos (todas las sedes). Los **reportes/dashboard/cierre por sede** = filtran por `sucursal` y son **privados de la sede** (solo esa sede + dueño/admin). |
| `Patient` | **No** — compartido | el paciente es del negocio; su expediente y su estado de cuenta lo siguen entre sedes. Opcional: `sucursal_origen` informativa |
| Catálogos (`ServiceConcept`, `LabAnalyte`, `DocumentTemplate`, `TreatmentPackage`, equipo, preguntas HC) | **No** (recomendado) | compartidos por el negocio; a futuro se podría permitir precio/override por sede |
| Expediente / Plan Integral / Calendarización | **No** | son del paciente (el expediente sigue al paciente entre sedes); la *cita/sesión* sí tiene sede vía Appointment |
| `ClinicSettings` | **No** al inicio | opcional a futuro: override de dirección/teléfono/membrete por sede en los PDFs |

Relación **usuario ↔ sucursal** (quién opera en qué sede):

```
MembershipSucursal(TenantAwareModel)   # o M2M en TenantMembership
  membership  FK TenantMembership
  sucursal    FK Sucursal
```

- El **rol** sigue siendo por tenant (owner/admin/doctor/…).
- La **sucursal** define en qué sedes puede operar ese usuario. Owner/admin: todas.

## 6. Seguridad y RLS (punto importante)

- **RLS se queda igual: la barrera dura sigue siendo el `tenant_id`.** Las sucursales del
  mismo negocio comparten tenant, así que RLS **no** las separa. El filtrado por sucursal
  es (1) UX + (2) validación en la **capa de servicio** (que el actor pertenezca a la
  sucursal de la acción), NO una muralla de base de datos.
- Esto es aceptable y normal para sucursales de UN mismo dueño. **Si se exigiera** que
  una sede jamás vea datos de otra ni por error de código, sería Fase 4: añadir
  `sucursal_id` a las políticas RLS (más costo, doble dimensión de GUC) — o irse a Opción B.
- Regla de oro a mantener: **toda tabla nueva sigue siendo `TenantAwareModel` con su RLS
  por tenant** (el test guardián lo exige). La sucursal es un campo más, no reemplaza el
  tenant.

## 7. Impacto por módulo (qué hay que tocar)

- **tenancy:** +`Sucursal`, +`MembershipSucursal`, endpoint `/me` devuelve las sucursales
  del usuario + la activa.
- **personal:** `Consultorio.sucursal`, `Doctor.sucursales` (M2M), `DoctorSchedule.sucursal`.
- **agenda:** `Appointment.sucursal`; la **disponibilidad** y el calendario se filtran por
  sede; el anti-empalme sigue por doctor/consultorio (ya cubre la sede vía consultorio).
- **finanzas:** `Charge`/`Payment.sucursal`; dashboard con **filtro por sucursal** +
  vista consolidada.
- **pacientes:** sin cambios (compartidos); opcional `sucursal_origen` informativa.
- **expediente / calendarización / plan integral / cotizaciones:** el documento es del
  paciente (no cambia); la sede entra por la cita/sesión.
- **plataforma (super-admin):** ver/gestionar las sucursales de cada tenant.
- **PDFs:** a futuro, membrete/dirección de la sucursal donde se atiende (Fase 3).
- **Frontend:** un **selector de sucursal** en la barra superior (parecido al "selector de
  clínica" que ya estaba pendiente para usuarios multi-clínica); la sede activa scopea
  agenda/personal/finanzas; sede por defecto al entrar; se manda al backend (header
  `X-Sucursal` o query) para filtrar.

## 8. Migración / compatibilidad

- Todos los FK `sucursal` nacen **nullable** → nada se rompe.
- Migración de datos: por cada tenant existente se crea una **"Sucursal Principal"**
  (`is_default=True`) y se asignan a ella los consultorios/doctores/citas actuales.
- El selector de sucursal arranca con la principal → experiencia idéntica para quien tiene
  una sola sede.

## 9. Plan por fases (si se aprueba la Opción A)

- **Fase 0 — Decisiones** (§10): responder las preguntas abiertas.
- **Fase 1 — Base multi-sede:** modelo `Sucursal` + sucursal por defecto + backfill +
  `Consultorio.sucursal` + `Doctor.sucursales` + **selector de sucursal** en la UI +
  scoping de **agenda y personal** por sede.
- **Fase 2 — Finanzas por sucursal:** ingresos/cargos por sede + reportes consolidados y
  filtrados.
- **Fase 3 — Operación fina:** `MembershipSucursal` (quién opera en qué sede) + horarios
  laborales por sede + membrete de la sede en los PDFs.
- **Fase 4 (opcional) — Muralla dura:** aislamiento por sucursal a nivel RLS, solo si el
  negocio lo exige.
- **Después:** "especialidades por sucursal" (requiere ANTES el catálogo de especialidades
  como entidad, que hoy tampoco existe).

## 10. Decisiones abiertas (para arrancar)

1. **¿Enfoque A o B?** (recomendado **A**: sucursal dentro del negocio, pacientes y
   catálogos compartidos.)
2. **Pacientes: ¿compartidos entre sucursales o separados por sede?** (recomendado
   **compartidos** — el expediente sigue al paciente.)
3. **Catálogos (servicios, precios, analitos, plantillas): ¿iguales en todas las sedes o
   distintos por sede?** (recomendado **compartidos**, con override por sede como mejora
   futura.)
4. **¿Un usuario/médico opera en una sola sede o puede en varias?** (recomendado **varias**;
   dueño/admin en todas.)
5. **¿Se necesita muralla DURA entre sedes (que una sede jamás vea datos de otra ni por
   bug)?** Si sí → Fase 4 / Opción B; si no → Opción A basta.
6. **Facturación/planes: ¿se cobra por negocio o por sucursal?** (afecta suscripciones.)

## 12. Rol "Administrador de sucursal" (modelo de acceso)

Además de dueño/admin del negocio, se agrega el **administrador de sucursal**: un admin
cuyo alcance es UNA (o varias) sucursal(es). Ej.: "Admin de Sucursal Centro" ve solo los
paneles/operación de Centro.

Modelo:
- Nueva relación **`MembershipSucursal`** (membership ↔ sucursal): en qué sedes opera cada
  usuario. Los roles siguen igual (owner/admin/doctor/nurse/reception/finance/readonly);
  lo nuevo es el **alcance de sucursal**.
- **Dueño (owner):** siempre TODAS las sedes (negocio completo). Ve consolidado y por sede
  (con un selector de sucursal).
- **Admin de sucursal:** rol `admin` asignado a UNA sede → administra/ve la agenda,
  personal, consultorios y **finanzas de SU sede**. No ve la caja/reportes de otras sedes.
- **Admin de negocio** (opcional): rol `admin` asignado a TODAS las sedes → como el dueño
  pero sin facturación/plan.
- **Finanzas / Recepción / Enfermería / Doctor:** su rol, acotado a su(s) sede(s) para lo
  operativo (agenda, caja de la sede); el **expediente y el estado de cuenta del paciente
  son compartidos** (los ven donde atiendan al paciente).
- La **sucursal activa** (selector en la barra) filtra lo "por sucursal"; lo "compartido"
  no se filtra por sede.

## 13. Matriz de visibilidad COMPLETA (compartido vs por sucursal)

Leyenda: **Compartido** = a nivel negocio, igual en todas las sedes. **Por sucursal** =
lleva `sucursal` y se filtra por sede. Todo sigue siendo `TenantAwareModel` con RLS por
tenant (la sucursal es un campo adicional, no reemplaza el tenant).

### Configuración del negocio
| Entidad | Alcance | Quién administra |
|---|---|---|
| `Tenant`, `Plan`, `TenantSubscription` (facturación del SaaS) | Compartido (negocio) | Solo **dueño** |
| `TenantMembership` (usuarios del negocio) | Compartido, con **alcance de sede** vía `MembershipSucursal` | Dueño (todos); admin de sede (usuarios de su sede) |
| `ClinicSettings` (marca/membrete), `ClinicTemplate`, `PatientCategory`, `ClinicFiscalConfig` (RFC), `DoctorUniversity`, `DoctorCredential` | Compartido (negocio) | Dueño/admin. *(Membrete/dirección por sede = mejora futura.)* |
| `ClinicTeamMember` (equipo del Plan Integral) | **Candidato a por sucursal** (cada sede su equipo) | Fase 3 |

### Personal y espacios — **POR SUCURSAL**
| Entidad | Alcance | Nota |
|---|---|---|
| `Doctor` | **Por sucursal** (M2M `sucursales`) | un médico puede estar en varias sedes |
| `Consultorio` | **Por sucursal** | el cuarto pertenece a una sede |
| `DoctorSchedule` (horario laboral) | **Por sucursal** | horario por sede |

### Agenda — **POR SUCURSAL**
| Entidad | Alcance | Nota |
|---|---|---|
| `Appointment` (citas) | **Por sucursal** | agenda independiente por sede |
| `AgendaBlock` (bloqueos/juntas) | **Por sucursal** | |
| `AgendaItemNote`, `AppointmentReminder` | **Por sucursal** (heredan de la cita) | el recordatorio se manda al paciente igual |
| `AppointmentType` (tipos/colores), `TenantAgendaConfig` (recordatorios) | Compartido (negocio) | *(override por sede = opcional)* |

### Pacientes — **COMPARTIDO**
| Entidad | Alcance | Nota |
|---|---|---|
| `Patient` | **Compartido** (negocio) | visible en cualquier sede; el nº de expediente es único del negocio |
| `PatientSequence` (folio) | Compartido | una numeración por negocio |
| *(opcional)* `Patient.sucursal_origen` | informativo | dónde se registró; no restringe |

### Expediente / clínico — **COMPARTIDO (sigue al paciente)**
| Entidad | Alcance | Nota |
|---|---|---|
| `Allergy`, `MedicalHistory`, `VitalSignsRecord`, `EvolutionNote`, `Addendum`, `Diagnosis`, `EvolutionImage`, `ClinicalSummary`, `TreatmentPlan`/`Item`/`Session`, `LongevityPlan` | **Compartido** | el registro clínico se ve en cualquier sede; queda marcado quién/dónde lo creó (vía la cita ligada). |
| `MedicalHistoryQuestion`, `DocumentTemplate`, `LabAnalyte` (catálogos clínicos) | Compartido (negocio) | mismas preguntas/plantillas/analitos en todas las sedes |

### Finanzas — **DUAL: cuenta del paciente compartida, reportes de sede privados**
| Entidad | Alcance | Nota |
|---|---|---|
| `ServiceConcept`, `TreatmentPackage`/`Item` (catálogo/precios) | Compartido (negocio) | *(precio por sede = opcional futuro)* |
| `Charge`, `Payment`, `PaymentAllocation`, `Quote`/`Item`, `CfdiDocument` | **DUAL** | pegados al `patient` → aparecen en su **estado de cuenta** en cualquier sede; y llevan **`sucursal`** (dónde se cobró/generó) → cuentan para los **ingresos/caja de esa sede**. |
| **Dashboard / Reportes / Cierre diario** (vistas) | **Por sucursal (PRIVADO)** | cada admin/finanzas ve la caja y reportes de SU sede; el **dueño** ve consolidado + por sede. **Esto es lo que pediste que fuera privado por sede.** |

### Transversal
| Entidad | Alcance | Nota |
|---|---|---|
| `Note` (notas) | Personal del usuario | no por sede |
| `Notification` (campana) | Personal del usuario | |
| `AuditLog` (bitácora) | Compartido (negocio) | filtrable por sede para el admin de sede; el dueño ve todo |

## 14. Quién ve qué — por rol y sede

| Área | Dueño | Admin de **Sucursal Centro** | Recepción/Enfermería de Centro | Doctor de Centro | Finanzas de Centro |
|---|---|---|---|---|---|
| Agenda | Todas las sedes (selector) | Solo Centro | Solo Centro | Solo Centro (sus citas) | — |
| Personal / consultorios | Todas | Solo Centro | Ver Centro | Ver Centro | — |
| **Pacientes (lista + datos)** | Todos | Todos (compartido) | Todos | Todos | Todos |
| **Expediente clínico** | Todos | Todos | Según rol clínico | Todos (sus pacientes) | No (rol no clínico) |
| **Estado de cuenta del paciente** | Todos | Todos | Todos | (según config) | Todos |
| **Caja / reportes / dashboard de finanzas** | Consolidado + por sede | **Solo Centro** | Cobrar en Centro | — | **Solo Centro** |
| Cotizaciones / Paquetes (catálogo) | Todas | Usar (compartido) | Usar | Usar | Ver |
| Config del negocio (marca, catálogos) | Editar | Ver (o editar lo de su sede) | — | — | — |
| Facturación del SaaS / plan | Solo dueño | No | No | No | No |
| Usuarios del negocio | Todos | Los de su sede | — | — | — |

> Regla mental simple: **el paciente y su información (clínica + su cuenta) es del
> NEGOCIO** (se ve en cualquier sede). **La operación y el dinero DE la sede** (agenda,
> personal, caja, reportes) **es de la sede**. El dueño ve todo.

## 11. Nota sobre "especialidades por sucursal"

Depende de DOS cosas que hoy no existen: (1) las **especialidades como entidad/plugin**
(hoy son texto libre) y (2) las **sucursales** (este documento). Una vez existan ambas,
"especialidades por sucursal" es solo una relación `Sucursal ↔ Specialty`. Es la última
capa, no la primera.
</content>
