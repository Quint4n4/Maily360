# Hallazgos de seguridad — Sucursales (F1-F4)

> Auditoría 2026-07-10 (equipo de 8 auditores + verificación adversarial). El workflow se
> cortó por límite de sesión a media verificación, PERO los hallazgos de abajo fueron
> **reproducidos con PoC real en el shell de Django por los propios auditores** ("VERIFICADO
> en shell"), así que NO dependen del pase adversarial que quedó incompleto.
>
> **NADA de esto está en producción** (todo local, sin push). No hay exposición activa.
>
> **ESTADO 2026-07-10 (tarde): clústeres A, B, C y D CORREGIDOS y verificados**
> (suite completa 3150 passed, 0 fallos, con 74 tests nuevos que reproducen cada exploit y
> confirman el bloqueo; E2E real de reagendar-entre-sedes y escalada de doctor = bloqueados).
> **NO se ha hecho push (decisión del dueño: sigue probando en local).**
>
> **SEGUNDA PASADA 2026-07-15 (barrido de verificación):** al cerrar el `PaymentDetailApi`
> pendiente se hizo un barrido de TODOS los endpoints de detalle/PDF/acción-por-id sobre
> objetos con sede. Se cerraron 3 huecos (el pendiente + 2 NUEVOS que la 1ª auditoría omitió):
> - ✅ **F1 — `PaymentDetailApi` (`apps/finanzas/views.py`)**: A7 aplicado a PAGOS. Ahora usa
>   `_scope_or_404(request, payment.sucursal_id, ...)`. Tests en test_sucursal_finanzas.py
>   (`TestPagosDetallePorIdAcotado`).
> - ✅ **F2 — `QuotePdfApi` (`apps/finanzas/views.py`)** [NUEVO]: `GET /cotizaciones/<id>/pdf/`
>   generaba el PDF (montos/paciente/conceptos) de una cotización de OTRA sede sin acotar —
>   misma clase que A6, pero se le escapó a la 1ª auditoría (cubrió detalle+acciones, no el PDF).
>   Ahora aplica `_scope_or_404`. Tests en `TestCotizacionesCicloVidaAcotado` (2 nuevos).
> - ✅ **F3 — `doctor_set_consultorios` (`apps/personal/services.py`)** [NUEVO]: validaba
>   tenant+activo pero NO `allowed_sucursales` (a diferencia de su hermano `doctor_set_sucursales`
>   ya arreglado en el clúster C) → un admin de Centro asignaba/quitaba un consultorio de Norte
>   (privado por sede, A5) a cualquier médico. Ahora aplica el mismo anti-escalada (diferencia
>   simétrica de consultorios → su sede ∈ allowed; owner exento; sede None legado pasa). Tests
>   en `TestDoctorSetConsultoriosEscalation` (5 nuevos).
>
> Salió LIMPIO en el barrido: `PeriodReportPdfApi` (congela `sucursal_scope_ids` en los params
> del job → el worker regenera con el alcance del actor); recetas/libro clínico (compartidos por
> diseño, NO deben acotarse por sede); detalle de cargo/cotización/pago/CFDI (ya acotados);
> `cfdi_issue` (valida la sede en el service). BAJO documentado: `AgendaItemNoteDetailApi`
> (borrar nota de agenda) no acota por la sede de la cita — vector práctico nulo (el `note_id`
> no se filtra por el estado de cuenta; listar notas exige la cita, que ya está acotada), pero
> es inconsistente; defensa en profundidad, sin corregir.
>
> **✅ Clúster E CERRADO (2026-07-15):** RLS por SUBCONSULTA al padre (sin migración de datos ni
> cambios a call sites `.add/.set/.remove`) en las tablas through auto de M2M entre modelos
> tenant-aware. Se cubrieron **3** tablas (2 del hallazgo + 1 que no estaba: `pacientes_patients_categories`):
> - `personal_doctors_sucursales`, `personal_doctors_consultorios` → migración
>   `apps/personal/migrations/0012_rls_doctor_m2m_through_tables.py` (reversible).
> - `pacientes_patients_categories` → migración `apps/pacientes/migrations/0015_rls_patient_categories_through.py` (reversible).
> - Guardián `apps/core/tests/test_rls_coverage.py` EXTENDIDO: ahora recorre los M2M con through
>   auto entre modelos tenant-aware y exige RLS (cualquier M2M nuevo así sin RLS rompe la suite).
>   Tests de aislamiento cross-tenant REAL (evalúan el `qual` instalado en `pg_policies`).
> - Nota conocida (ya documentada en el proyecto): la suite corre con el rol `mailysoft`
>   (SUPERUSER, exento de RLS aun con FORCE); por eso los tests evalúan el `qual` real de la
>   policy en vez de `COUNT(*)`. No es regresión nueva.
>
> **VEREDICTO 2026-07-15: suite COMPLETA 3167 passed, 0 fallos** (3150 previos + 17 nuevos:
> F1=3, F2=2, F3=5, Cluster E=7). mypy/ruff/black sin errores nuevos propios. TODO LOCAL, SIN PUSH.
>
> ---
> ## 🔴 VEREDICTO REVISADO 2026-07-16 — ❌ NO DESPLEGAR: clúster F abierto
>
> El **dueño, probando en local**, notó que veía el mismo personal en las 2 sedes. Al tirar del
> hilo apareció el **clúster F** (ver sección abajo): la app `tenancy` (gestión de miembros)
> **nunca supo de sucursales**. Dos exploits CRÍTICOS verificados con status 200:
> - **F1 — auto-promoción**: un admin de sede se hace `owner` con un PATCH a su propia membresía
>   → gana todas las sedes. **Esto anula TODO lo arreglado en A/B/C/D/E y F1-F3**: de nada sirve
>   blindar cargos, PDFs y agenda si el admin se auto-asciende.
> - **F2 — toma de cuenta**: ese mismo admin resetea la contraseña del DUEÑO y entra como él.
>
> Lección de método: las dos auditorías previas buscaron fugas *dentro* del sistema de sedes y
> `tenancy` quedó fuera del radar de ambas (no importa nada de `sucursal_scope`). **La próxima
> auditoría debe barrer por APP, no por feature** — cualquier app que gestione cuentas, roles o
> permisos entra, sepa o no de sucursales.
>
> **✅ CLÚSTER F CERRADO (2026-07-16):** app `tenancy` ahora consciente de sedes.
> - **Lista** (`membership_list`) acotada por `sucursal_scope_ids` (sede activa); owner siempre
>   aparece; sin sede asignada → sede por defecto. **Autorización** (PATCH/avatar/create) contra
>   `allowed_sucursales`: no-owner solo toca a personal de sus sedes, no puede tocar a un owner ni
>   ascender/crear a `owner`; owner puede todo (incl. resetear a otro owner). `member_create` asigna
>   la sede del nuevo miembro (activa > sedes del actor no-owner; nunca la default ajena).
> - **Huecos extra que cerró el agente:** `member_set_avatar`/`member_clear_avatar` no tenían NINGUNA
>   autorización (F5-bis). Y evitó una **regresión**: `plataforma.tenant_and_owner_create` usa
>   `member_create` para el 1er owner de una clínica nueva con un actor de plataforma SIN membresía
>   → excepción acotada de bootstrap (solo si el tenant no tiene miembros y el rol pedido es `owner`).
> - **Re-verificación independiente (mía, con los exploits que antes daban 200):** F1 auto-promoción
>   → 400 (sigue admin); F2 reset de contraseña del dueño → 400 (intacta); F3 → el admin de Norte
>   solo ve 2 filas (él + el owner), no al de Centro; POSITIVO → el admin SÍ gestiona a su propia
>   gente. Tests del agente: tenancy 117 / clinica 258 / core 253 / plataforma 216 = **844 passed**.
> - **Frontend:** `web-soft/src/hooks/equipo.ts` — la `queryKey` ahora incluye la sede activa (igual
>   que agenda) para que la lista refresque al cambiar de sucursal; `tsc -b` verde. El header
>   `X-Sucursal-Id` ya lo manda `http.ts`.
>
> **Suite backend COMPLETA: 3191 passed, 0 fallos** (incluye clúster F + refinamiento F' de
> jerarquía de roles). `tsc -b` del frontend verde. TODO LOCAL, SIN PUSH.
> Re-verificado independiente (F'): admin de Norte ve solo [él + operacionales de su sede], no
> puede crear admin/owner (400), no puede ascender un doctor a admin (400); owner ve/crea todo.
>
> **PENDIENTE antes de push:** re-correr la auditoría adversarial completa **barriendo por APP, no
> por feature** (lección del clúster F: `tenancy` se le escapó a las 2 auditorías previas por no
> importar `sucursal_scope`; cualquier app que gestione cuentas/roles/permisos entra al barrido).
>
> Aviso de deploy: los clientes de una sola sede NO se afectan (todo queda bajo "Sucursal
> Principal" por el backfill; un admin cuya membresía cubre la única sede recibe vista
> consolidada). Solo importaría si en producción hubiera ya varios admins que dependieran del
> viejo atajo "admin ve todas" — no es el caso hoy.
>
> ---
> **VEREDICTO ORIGINAL (histórico): ❌ NO desplegar hasta corregir el clúster A, B y C.**

## Causa raíz común
La Fase 3 aplicó el scoping por sede a los endpoints de **LISTA** y **CREAR**, pero **NO** a
los de **DETALLE / ACCIÓN-por-id** (PATCH/DELETE/acciones). Los selectors `*_get` solo
filtran por tenant, no por sede; y los services de acción no validan `allowed_sucursales`.
Como el **id de cualquier objeto se obtiene del estado de cuenta del paciente** (compartido
a propósito), un admin acotado a una sede puede operar sobre objetos de OTRA sede por su id.

---

## Clúster A — Endpoints de detalle/acción por id sin filtro de sede

Patrón de arreglo para TODOS: un helper `*_get_scoped(request, id)` que aplique
`sucursal_id__in=sucursal_scope_ids(request)` (dejando pasar `sucursal IS NULL` legado) →
404 fuera de alcance; y en los services por id, validar `allowed_sucursales(user=..., tenant=..)`.

| # | Sev | Endpoint / archivo | Qué permite (VERIFICADO ✅ = PoC corrido) |
|---|---|---|---|
| A1 | 🔴 CRÍTICO | `appointment_reschedule` — `apps/agenda/services.py:935` | Reagendar citas de Norte **y MOVER citas de Centro a Norte**. ✅ Es el único write de agenda que nunca llama `resolve_write_sucursal`. |
| A2 | 🟠 ALTO | Citas por id: PATCH/cancelar/estado/reactivar — `apps/agenda/views.py:439,551,637` | Editar/cancelar/marcar no-asistió/reactivar citas de otra sede. |
| A3 | 🟠 ALTO | Bloqueos/eventos PATCH/DELETE — `apps/agenda/views.py:925` (`agenda_block_get`) | Mover/borrar bloqueos de otra sede (rompe el anti-empalme de esa sede). |
| A4 | 🟠 ALTO | Horarios DELETE — `apps/personal/views.py:639` (`schedule_get`) + listado `:565` | Borrar el horario laboral de un médico en otra sede. |
| A5 | 🟠 ALTO | Consultorios crear/PATCH/DELETE — `apps/personal/views.py:392,483,509` | Crear consultorio en Norte con `sucursal_id` explícito; reasignar/dejar huérfano/borrar consultorios de Norte. ✅ |
| A6 | 🟠 ALTO | Cotizaciones aceptar/enviar/rechazar — `apps/finanzas/views.py:533,552,513` (`quote_get`) | Operar cotizaciones de otra sede; **aceptar CREA `Charge` en la caja de Norte**. |
| A7 | 🟠 ALTO | Cargos cancelar — `apps/finanzas/views.py:721` (`charge_get`) | Anular ingresos de Norte (altera su corte de caja). |
| A8 | 🟠 ALTO | Calendarización agendar/quitar sesión — `apps/expediente/views_calendarizacion.py:411,450` | Mover/cancelar citas de sesiones en otra sede (usa A1 como raíz). |

## Clúster B — Fuga de LECTURA al desactivar una sede (diseño de `sucursal_scope_ids`)

- 🔴 **CRÍTICO/ALTO — `apps/clinica/sucursal_scope.py:387`.** `sucursal_scope_ids` infiere
  "alcance TOTAL → None (sin filtro)" comparando `len(allowed_ids) >= total_sucursales_ACTIVAS`.
  Al **desactivar/borrar una sede** (Norte), un admin acotado a las restantes pasa a "cubrir
  todas las activas" → devuelve `None` → **todos** los reportes privados (cierre, dashboard,
  RFM, antigüedad, listados de cargos/pagos/cotizaciones) dejan de filtrar y le muestran la
  **caja histórica de Norte** (las filas conservan `sucursal_id=Norte`). ✅ VERIFICADO
  (0.00 con Norte activa → 7777.00 tras desactivarla).
- **Arreglo:** no inferir "total" por conteo. Devolver `None` SOLO si el rol es `owner` (o si
  la membresía cubre TODAS las sedes, activas **e** inactivas). En cualquier otro caso,
  devolver la **lista explícita** de ids permitidos. Decidir aparte qué hacer con las filas
  legado `sucursal IS NULL`.

## Clúster C — Escalada por gestión de sucursales y médicos

- 🔴 **CRÍTICO — `SucursalDetailApi` (`apps/clinica/views.py:1017`).** PATCH/DELETE de
  sucursal solo gatea por rol; un admin de Centro puede **editar/marcar-default/DESACTIVAR
  Norte**. ✅ Y desactivar Norte dispara el bug B (gana lectura de todas las sedes).
  **Arreglo:** `_get_or_404` debe resolver contra `allowed_sucursales(user=request.user, ...)` (404 si no está).
- 🟠 **ALTO — `doctor_set_sucursales` (`apps/personal/services.py:280`).** No valida
  `allowed_sucursales` (a diferencia de `membership_sucursales_set`, que sí lo hace bien) →
  un admin de Centro reasigna en qué sedes atiende **cualquier** médico. ✅ VERIFICADO.
  **Arreglo:** validar que las sedes otorgadas Y quitadas estén en `allowed_sucursales` del actor.

## Clúster D — CFDI quedó fuera de la Fase 3

- 🟠 **ALTO — `apps/finanzas/selectors.py:278` (`cfdi_list`) y `views.py:838,871`.** El
  listado/detalle de CFDI **no se acota por sede** (único listado financiero sin
  `sucursal_scope_ids`), y `CfdiDocument` **no recibió** el campo `sucursal`. Un admin de
  Centro ve montos/RFC/paciente de las facturas de Norte. ✅ VERIFICADO.
- 🟡 **MEDIO — `cfdi_issue` (`services.py:911`) y `CfdiCancelApi`.** Timbrar/cancelar CFDI no
  valida la sede del pago → un admin de Centro puede **timbrar o cancelar** CFDI de Norte
  (integridad fiscal ante el SAT).
- **Arreglo:** dar a `CfdiDocument` un `sucursal` (heredado del `payment`, con backfill),
  acotar `cfdi_list` con `sucursal_scope_ids`, y validar la sede en emitir/cancelar/detalle.

## Clúster G — La app `notas` nunca supo de sucursales (encontrado por el DUEÑO probando, 2026-07-16)

> Tercer caso del MISMO patrón (app que no importa `sucursal_scope`), otra vez destapado por el
> dueño probando: como admin de Norte veía los avisos de TODAS las sedes. NO es fuga de datos
> sensibles (los avisos están para leerse) — es correctitud/UX de comunicación entre sedes.

**Modelo actual `Note`:** `scope` personal/role/all. Personales = privadas del autor (OK). Avisos
(role/all) se difundían a todo el tenant sin sede.

**Decisión del dueño (2026-07-16):** tres tipos de aviso:
1. **De sucursal (normal):** lo crea el ADMIN, acotado a SU sede (forzado). Solo lo ve esa sede.
2. **Importante del DUEÑO:** el owner elige la sede (una, o null=todas) y puede marcarlo `is_important`
   (destacado). Solo el owner puede marcar importante y/o mandar a "todas las sedes".
3. **De mantenimiento/sistema (tipo 3):** lo manda Maily/plataforma a TODAS las clínicas.
   **PENDIENTE — feature aparte del portal de plataforma, NO implementada aún.**

**Implementado (tipos 1 y 2):**
- Modelo: `Note.sucursal` (FK null=todas) + `Note.is_important`. Migraciones `notas/0003` (esquema)
  y `notas/0004` (backfill → sucursal=null, is_important=false; legado sigue clínica-completa).
- `note_create` + `_resolve_broadcast_sucursal`: owner elige sede/importante libremente; no-owner
  forzado a su sede vía `resolve_write_sucursal` (valida `allowed_sucursales`), `is_important=True`
  RECHAZADO. `scope=all` ahora también lo puede el admin (acotado a su sede), antes owner-only.
- `note_list_visible(sucursal_ids)`: aviso visible si `sucursal IS NULL OR sucursal ∈ scope`;
  personales sin cambios. La VISTA pasa `sucursal_scope_ids(request)`.
- Detalle/editar/borrar acotados por sede (404 fuera de alcance).
- **Bonus:** el agente cerró de paso una fuga en las NOTIFICACIONES (campana): `_filter_recipients_by_sucursal`
  evita notificar un aviso de una sede a quien no la puede ver.
- Frontend: `hooks/notas.ts` (sede en queryKey), `NotaCard` (badge "IMPORTANTE" + etiqueta de sede),
  `NuevaNotaModal` (el admin crea avisos de su sede; el dueño elige sede + toggle importante), `types/nota.ts`.
- Tests: `apps/notas/tests/test_sucursal_notas.py` (11) — admin acotado, no-importante, no-sede-ajena;
  owner todas+importante; visibilidad por sede; personales intactas; ruta HTTP. `apps/notas`+`notificaciones` = 146 passed. `tsc -b` verde.

## Clúster F — La app `tenancy` nunca supo de sucursales (encontrado por el DUEÑO probando, 2026-07-16)

> **El más grave de toda la iniciativa: F1 anula el modelo completo de sucursales.**
> Lo destapó el dueño al notar que veía el mismo personal en las 2 sedes. La 1ª auditoría y
> el barrido de 2ª pasada NO lo vieron porque ambos buscaron fugas *dentro* del sistema de
> sedes (agenda/finanzas/personal/expediente/clinica), y `tenancy` no importa NADA de
> `sucursal_scope` — quedó fuera del radar de los dos.

**Causa raíz:** el modelo viejo asumía `admin` = *persona de confianza total de una clínica de
una sola sede* (gestionar cuentas ERA su trabajo). Al introducir el **"administrador de
sucursal"** como rol LIMITADO, esa suposición se volvió un agujero. `member_update` /
`member_create` solo validan que el rol exista (`_VALID_ROLES`), sin autorizar al actor;
`MemberPermission` deja pasar a owner y admin por igual.

| # | Sev | Qué permite (VERIFICADO ✅ con exploit real, status 200) |
|---|---|---|
| F1 | 🔴 CRÍTICO | **Auto-promoción**: un admin acotado a Norte hace `PATCH /miembros/<su_propia_id>/ {"role":"owner"}` → se vuelve owner → gana TODAS las sedes. **Hace inútil todo lo demás** (A/B/C/D/F1-F3): ¿para qué blindar cargos/PDF/agenda si el admin entra por la puerta grande? ✅ `status=200 rol_final=owner` |
| F2 | 🔴 CRÍTICO | **Toma de cuenta**: `PATCH /miembros/<id_del_dueño>/ {"password":"..."}` → el admin de Norte cambia la contraseña del DUEÑO y entra como él. ✅ `status=200 password_del_dueno_cambiada=True` |
| F3 | 🟠 ALTO | `GET /miembros/` (`membership_list()`) no filtra por sede → el admin de Norte ve nombres/correos/roles de TODO el personal, incluido el de Centro. (Es lo que vio el dueño.) |
| F4 | 🟠 ALTO | `member_create` no asigna sede → el miembro nuevo cae en la sede POR DEFECTO. Un admin de Norte da de alta a alguien y aterriza en **Centro**; y puede crear directamente un `owner` (escalada por proxy). |
| F5 | 🟡 MEDIO | `MemberDetailApi` / `MemberAvatarApi` resuelven por id solo con tenant → tocar/mirar miembros de otra sede. |

**Decisiones del dueño para el arreglo (2026-07-16):**
- **D1 — Lista de Equipo:** se filtra por la SEDE ACTIVA del selector (igual que agenda/finanzas).
  Miembro SIN sede asignada → aparece en la sede POR DEFECTO.
- **D2 — Admin de sucursal:** gestiona solo al personal de SUS sedes; el personal que da de alta
  cae en SU sede.
- **D3 — Contraseñas:** el `owner` resetea a cualquiera (incluido otro owner).

**REFINAMIENTO F' (2026-07-16, 2ª ronda — el dueño notó, como admin de Norte, que veía a los
DUEÑOS en la lista y que podía dar de alta administradores):** la primera versión del arreglo
dejaba "los owners siempre visibles" y solo bloqueaba crear/ascender a `owner` (permitía crear
`admin`). Corregido a **jerarquía estricta de roles**:
- Definir **operacionales = todos los roles EXCEPTO `owner` y `admin`** (doctor/nurse/reception/
  finance/readonly), derivado de las choices.
- Actor `owner`: sin cambios, ve/crea/gestiona a cualquiera.
- Actor NO owner (admin de sucursal), dentro de `allowed_sucursales`: **VE** solo a operacionales
  de sus sedes + a sí mismo (nunca owners ni OTROS admins); **CREA/EDITA/GESTIONA** solo roles
  operacionales (no puede crear ni ascender a `admin`/`owner`, ni tocar a un `admin`/`owner`).
- `_member_get_or_404`: para actor no owner, target no operacional → 404 (no revelar).
- **Frontend (`web-soft`):** `EquipoTab` oculta el grupo "Dueño" a los no-owner; `NuevoMiembroDrawer`
  y `MiembroDetalleDrawer` solo ofrecen roles operacionales a los no-owner; `hooks/miembros.ts`
  mete la sede activa en la queryKey (refresca al cambiar de sede). `tsc -b` verde.
- Nota: `/clinica/equipo/` (roster del Plan de Longevidad, `ClinicTeamMember`) es OTRA cosa, sin
  campo `sucursal` → tenant-level/compartido, NO es fuga de sede.

**Distinción clave del arreglo (no la pierdas):** `sucursal_scope_ids(request)` = filtro de VISTA
(la sede del selector) → se usa para **listar**. `allowed_sucursales(user, tenant)` = frontera de
PERMISO → se usa para **autorizar acciones**. Si autorizaras con el selector, el dueño parado en
Centro no podría editar a un miembro de Norte.

## Clúster E — M2M through sin RLS (defensa en profundidad, BAJO) — ✅ RESUELTO 2026-07-15 (ver bloque de estado arriba)

- 🔵 **BAJO — `personal_doctors_sucursales`** (y el preexistente `personal_doctors_consultorios`).
  La tabla intermedia autogenerada del M2M `Doctor.sucursales` **no tiene RLS ni `tenant_id`**,
  y el guardián `test_rls_coverage.py` no la detecta (solo mira modelos `TenantAwareModel`,
  no los through auto). No hay exploit hoy (la capa de app filtra), pero rompe el patrón de
  "toda tabla nueva con RLS". **Arreglo:** extender el guardián para cubrir los through de M2M
  + convertir el M2M en un through explícito `TenantAwareModel` con su RLS (patrón de
  `MembershipSucursal`).

---

## Lo que salió LIMPIO (verificado)
- Las **dos tablas propias** (`clinica_sucursales`, `tenancy_membership_sucursales`) tienen
  RLS correcta (ENABLE+FORCE, USING **y** WITH CHECK con `OR current_tenant_id() IS NULL`).
- El aislamiento entre **clínicas (tenants)** sigue intacto (RLS por tenant no se debilitó).
- Las rutas de **CREAR** cita/cargo/pago/cotización/bloqueo/horario/consultorio SÍ validan la
  sede (`resolve_write_sucursal` con `user`). El agujero está en editar/actuar por id.
- El **estado de cuenta del paciente compartido** y la **disponibilidad global del médico**
  funcionan como se diseñó (no son bugs).
- `membership_sucursales_set` implementa bien la regla anti-escalada (es el patrón a copiar).

## Nota de método
El pase de verificación adversarial (3 escépticos por hallazgo) quedó incompleto por el
límite de sesión; el "47 confirmados" que reportó el workflow está **inflado** (los votos que
faltaron contaron como "no refutado"). Este documento se queda solo con los hallazgos que los
auditores **reprodujeron con PoC**. Faltó terminar de leer 5 lentes (alcance, lectura, idor,
frontend, completitud) — sus hallazgos probablemente solapan con A/B/C/D; revisar el journal
`wf_f96a7d2f-caa/journal.jsonl` al retomar.
</content>
