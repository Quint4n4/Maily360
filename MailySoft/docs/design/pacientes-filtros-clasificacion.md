# Pacientes — filtros por visita + clientes potenciales + favoritos/VIP + etiquetas

> Implementado durante el sprint de **2026-06-16**.
> Actualizado **2026-06-23**: etiquetas de pacientes (M2M con catálogo), fusión de Favoritos/VIP como etiquetas del sistema.
> Estado: **IMPLEMENTADO** (backend + frontend). Frontend compila; backend con suite en verde (87 tests nuevos en 2026-06-16; ampliados en 2026-06-23 con tests de etiquetas y clasificación sobre el nuevo modelo).
> Backend: `apps/pacientes` (modelo, selector `patient_list`, service `patient_set_classification`, endpoint `/clasificacion/`) + `apps/agenda` (`Appointment.reschedule_count`) + `apps/clinica` (`PatientCategory` con campo `kind`).
> Frontend: `web-soft` (página `ContactosPage`, hooks/api/tipos de paciente, reutiliza `MiniCalendario`).

---

## 1. Objetivo

Hacer el área de Pacientes mucho más útil para el día a día de la clínica:

1. **Filtrar la lista** por cuándo se atendió al paciente: Recientes, Esta semana, Este mes, o un **rango personalizado de fechas** (con mini-calendarios).
2. Un apartado **"Clientes potenciales"**: gente que mostró interés (agendó y luego canceló o reagendó) pero **nunca llegó a atenderse** — para darles seguimiento comercial.
3. Marcar pacientes como **⭐ Favorito** y **👑 VIP** para tenerlos visibles y darles seguimiento preferente.

---

## 2. Decisiones tomadas (locked)

- **D-A · Favoritos y VIP son de TODA la clínica.**
  _(Decisión original 2026-06-16)_ No por usuario; lo que marca recepción lo ven médicos y dueño. Si en el futuro se quiere "mis favoritos" por usuario, sería una tabla aparte.

  > **Evolución 2026-06-23:** `is_favorite` e `is_vip` dejaron de ser `BooleanField` en `Patient`. Ahora son **etiquetas del sistema** (`PatientCategory` con `kind=favorite` / `kind=vip`), parte del mismo catálogo M2M `Patient.categories`. El principio de que Favorito/VIP son de toda la clínica se mantiene intacto; solo cambia la implementación. Los campos `is_favorite`/`is_vip` se siguen exponiendo en el serializer (derivados del prefetch de etiquetas) para no romper la UI existente. Ver §3.1 y §3.3-evolución.

- **D-B · "Visto" = cita ATENDIDA.** El "último visto" de un paciente se deriva de su cita con `status=attended` más reciente (`last_seen`). No se desnormaliza ningún campo: se calcula con anotaciones en el selector (siempre exacto). Aprovecha el índice `appt_patient_hist_idx`.
- **D-C · "Esta semana" = semana CALENDARIO (lunes–domingo)** en la zona horaria de la clínica (`America/Mexico_City`). Confirmado con el dueño 2026-06-16: NO es una ventana móvil de "últimos 7 días". Consecuencia esperada: a inicios de semana el apartado puede salir vacío si nadie se ha atendido aún esos días (no es bug).
- **D-D · "Clientes potenciales" = 0 citas atendidas Y (canceló O reagendó).** Para detectar "reagendó" se agregó `Appointment.reschedule_count` (contador que sube en cada reagendamiento). Un paciente que ya tiene UNA cita atendida **no** es potencial, aunque también haya cancelado.
- **D-E · "Por fecha" = rango entre dos fechas** (date_from, date_to), ambas requeridas, `date_to` inclusive. Se eligen con dos mini-calendarios (Desde / Hasta).
- **D-F · Disponibilidad de datos siempre anotada.** El selector anota `last_seen`, `attended_count`, `cancelled_count`, `rescheduled_count` SIEMPRE, para que el serializer los exponga sin romper el endpoint de detalle (usa `getattr` tolerante).
- **D-G · Etiquetas como M2M, Favorito/VIP como etiquetas del sistema (2026-06-23).** Las etiquetas libres y las de sistema (Favorito/VIP) usan el mismo modelo `PatientCategory` y la misma relación `Patient.categories`. Las etiquetas de sistema tienen `kind != custom`, no se pueden borrar ni renombrar (propiedad `is_system`), y cada clínica tiene exactamente una por tipo (constraint de unicidad en BD). El médico puede asignar varias etiquetas a un paciente al editarlo; el filtro por etiqueta en el panel se hace con el parámetro `category_id` (sin N+1 gracias al prefetch).
- **D-H · Migración de datos de Favorito/VIP (2026-06-23).** Las clínicas existentes reciben las etiquetas de sistema vía migración de datos (`0010_migrar_favorito_vip_a_etiquetas.py`): se siembran `PatientCategory(kind=favorite)` y `kind=vip` por clínica y se migran los pacientes ya marcados con los `BooleanField` anteriores. Las clínicas nuevas las reciben automáticamente en `create_clinic` (via `seed_system_patient_categories` en `apps/plataforma`). Los `BooleanField` `is_favorite`/`is_vip` se eliminaron del modelo con la migración `0011_remove_patient_is_favorite_remove_patient_is_vip`.

---

## 3. Backend

### 3.1 Modelos
_(Estado original 2026-06-16, actualizado 2026-06-23)_

- `Patient` (`apps/pacientes/models.py`):
  - ~~`is_favorite` / `is_vip` (BooleanField)~~ — **eliminados** en 2026-06-23 (migración `0011_remove_patient_is_favorite_remove_patient_is_vip`).
  - `categories` — `ManyToManyField("clinica.PatientCategory", blank=True, related_name="patients")`. Las etiquetas del catálogo (incluyendo Favorito y VIP) viven aquí.
  - `category` (CharField legacy) — se conserva por compatibilidad con la v1; la clasificación nueva usa `categories`.
- `PatientCategory` (`apps/clinica/models.py`):
  - `name` (CharField), `is_active`, `deleted_at` (baja lógica).
  - `kind` (CharField, choices `custom`/`favorite`/`vip`, default `custom`, db_index) — **nuevo 2026-06-23**. Las etiquetas `favorite`/`vip` son del sistema: no se borran ni renombran (propiedad `is_system`).
  - Constraints: unicidad de nombre por tenant en activos; unicidad de una etiqueta por `kind` no-custom por clínica (`clinic_category_one_system_per_kind`).
- `Appointment` (`apps/agenda/models.py`): `reschedule_count = PositiveSmallIntegerField(default=0)`.
- `appointment_reschedule` hace `reschedule_count += 1` en cada reagendamiento (incluido cuando reactiva una cancelada). `appointment_reactivate` (mismo horario) **no** lo incrementa.

### 3.2 Selector — `patient_list`
`patient_list(*, search="", segment="all", date_from=None, date_to=None, category_id=None) -> QuerySet[Patient]`

Anota siempre: `last_seen`, `attended_count`, `cancelled_count`, `rescheduled_count`. Incluye `prefetch_related("categories")` para evitar N+1 al serializar etiquetas. Segmentos:

| `segment` | Regla | Orden |
|---|---|---|
| `all` | todos los activos | -created_at |
| `recent` | con `last_seen` no nulo | -last_seen |
| `week` | atendidos en la semana calendario actual | -last_seen |
| `month` | atendidos en el mes calendario actual | -last_seen |
| `date` | atendidos entre `date_from` y `date_to` (inclusive) | -last_seen |
| `potential` | `attended_count=0` Y (`cancelled_count>0` O `rescheduled_count>0`) | -created_at |
| `favorites` | ~~`is_favorite=True`~~ → **`categories__kind="favorite"`** (2026-06-23) | -created_at |
| `vip` | ~~`is_vip=True`~~ → **`categories__kind="vip"`** (2026-06-23) | -created_at |

Parámetro adicional **`category_id`** (UUID, opcional, 2026-06-23): filtra por etiqueta del catálogo, combinable con cualquier segmento. Un id ajeno al tenant no devuelve nada (el join contra `PatientCategory` ya está aislado por `TenantManager`).

Los filtros temporales usan `Exists(Appointment.objects.filter(...))` para no multiplicar filas por JOIN. Los límites de semana/mes/rango se calculan en la zona local del proyecto y se convierten a UTC (helpers `_week_bounds`, `_month_bounds`, `_date_range_bounds`).

### 3.3 Service + endpoint de clasificación
_(Actualizado 2026-06-23 — el mecanismo interno cambió; la interfaz de la API es compatible)_

- `patient_set_classification(*, patient, user, is_favorite=None, is_vip=None) -> Patient`: antes escribía `BooleanField`; ahora **agrega o quita la etiqueta del sistema** (`PatientCategory kind=favorite/vip`) de la relación `categories`. Solo actúa sobre los parámetros que no sean None; si ambos son None no escribe.
- `POST /api/v1/pacientes/<uuid>/clasificacion/` body `{is_favorite?, is_vip?}` → 200 con el paciente. Permiso `PatientPermission` (owner/admin/doctor/nurse/reception; readonly NO). La interfaz de la API no cambió.

### 3.3-evolución · Serializer `PatientOutputSerializer`
_(2026-06-23)_

`is_favorite` e `is_vip` siguen presentes en el output pero ahora son `SerializerMethodField` **derivados** del prefetch de categorías:
- `get_is_favorite` → `any(c.kind == "favorite" for c in obj.categories.all())`
- `get_is_vip` → `any(c.kind == "vip" for c in obj.categories.all())`
- `get_categories` → lista de `{id, name}` solo para etiquetas `kind=custom` (las de sistema se exponen por sus campos propios).

Campo nuevo `categories` en el output: lista de las etiquetas personalizadas del paciente (excluye Favorito/VIP que ya van en sus campos propios).

### 3.4 Service — `patient_update`
_(2026-06-23)_ Acepta el campo opcional `category_ids` (lista de UUIDs). Si se provee, se aplica como `patient.categories.set(cats)` usando `PatientCategory.objects.filter(id__in=..., is_active=True, deleted_at__isnull=True)`. `category_ids=None` (no enviado) = sin cambio en etiquetas; lista vacía = quitar todas. Solo se asignan categorías del tenant activo.

### 3.5 Endpoint de lista (ampliado)
`GET /api/v1/pacientes/?segment=&date_from=&date_to=&search=&category_id=`. Si `segment=date` sin ambas fechas → 400. El output incluye `is_favorite`, `is_vip` (derivados), `categories` (etiquetas custom), `last_seen_at`, `attended_count`.

### 3.6 Migraciones
_(Históricas 2026-06-16 + nuevas 2026-06-23)_

- `pacientes/0007_patient_is_favorite_is_vip.py` — histórica (creó los BooleanField).
- `agenda/0010_appointment_reschedule_count.py`
- `pacientes/0008_merge_20260616_1224.py` — merge para resolver dos hojas `0006`. Ver §6.
- `clinica/0009_patientcategory_kind_and_more.py` — añade `kind` a `PatientCategory` y su constraint de unicidad.
- `pacientes/0009_patient_categories_alter_patient_category.py` — crea la relación M2M `Patient.categories` (tabla `pacientes_patient_categories`).
- `pacientes/0010_migrar_favorito_vip_a_etiquetas.py` — migración de datos: siembra `PatientCategory(kind=favorite/vip)` por cada clínica y re-asigna los pacientes que tenían los BooleanField en True.
- `pacientes/0011_remove_patient_is_favorite_remove_patient_is_vip.py` — elimina los BooleanField del modelo.

### 3.7 Tests
_(2026-06-16)_ 87 tests nuevos en `test_segmentos_selectors.py` (41), `test_clasificacion_services.py` (13), `test_clasificacion_api.py` (23) y `test_reschedule_count.py` (10). Suite en verde en ese hito (526 total).

_(2026-06-23)_ Ampliados: `test_clasificacion_services.py`, `test_clasificacion_api.py` y `test_segmentos_selectors.py` reescritos para el nuevo modelo de etiquetas; nuevo `test_etiquetas.py` (100 tests) cubre asignación M2M, filtro por `category_id`, aislamiento multi-tenant, etiquetas de sistema no borrables y la integración Favorito/VIP. Cifra actualizada de tests: ver suite real con `pytest apps/pacientes/ -q`.

---

## 4. Frontend (`web-soft`)

_(Estado original 2026-06-16, actualizado 2026-06-23)_

- **Tipos** (`types/paciente.ts`): `PatientOut` tiene `is_favorite`, `is_vip` (derivados), `last_seen_at`, `attended_count`. Nuevo en 2026-06-23: `categories: Array<{id: string; name: string}>` (etiquetas custom). `PatientSegment` y `PatientClassifyInput` sin cambio de interfaz.
- **API** (`api/pacientes.ts`): `listPatients` acepta `segment`/`date_from`/`date_to`/`category_id` (2026-06-23); `setPatientClassification` sin cambio de interfaz.
- **Hooks** (`hooks/pacientes.ts`): `usePatients` acepta `categoryId` adicional (2026-06-23).
- **UI** (`pages/ContactosPage.tsx`):
  - **Barra de chips** dorados: Todos · Recientes · Esta semana · Este mes · 📅 Por fecha · Clientes potenciales · ⭐ Favoritos · 👑 VIP + chips de **etiquetas custom** del catálogo (2026-06-23): se renderizan dinámicamente, al hacer clic pasan `category_id` al filtro.
  - El chip **📅 Por fecha** despliega dos `MiniCalendario` (Desde / Hasta); el "Hasta" usa `min=dateFrom`.
  - En cada tarjeta: botón **⭐ favorito** y **👑 VIP** (toggle de 1 clic, conservan estrella/corona, funcionan sobre etiquetas de sistema — la UI es la misma que antes), **borde dorado** en las VIP, y **"Última: <fecha real>"** (de `last_seen_at`) o "Sin citas atendidas".
  - Las etiquetas custom asignadas al paciente se muestran en la tarjeta.
  - Mensaje de vacío a la medida de cada segmento.
- **Formulario de paciente** (`pacienteForm.tsx`, 2026-06-23): selector de etiquetas del catálogo al crear/editar un paciente; envía `category_ids`.
- **Sección de catálogo** (`SeccionCategorias.tsx`, 2026-06-23): gestión del catálogo de etiquetas en Mi Consultorio (crear, editar, desactivar etiquetas custom; las de sistema no se pueden borrar/renombrar).
- Helper nuevo `formatFechaCorta(iso)` en `lib/fecha.ts` ("3 jun 2026").

---

## 5. Comportamiento esperado (no es bug)

A inicios de semana, **"Esta semana" puede salir vacío** aunque "Recientes" y "Este mes" muestren pacientes: si la última cita atendida fue la semana pasada, cae en el mes pero no en la semana calendario actual. Ejemplo real (2026-06-16, martes; semana 15–21 jun): pacientes atendidos el 8 y 12 jun aparecen en Recientes y Este mes, pero no en Esta semana.

---

## 6. Nota de migraciones / coordinación

`0006_patient_nom004_fields` (campos NOM-004 del paciente, p. ej. `address_street`) viene de **otra sesión paralela** (trabajo de Expediente Clínico) y estaba **sin commitear**. Coincidió en el número 0006 con `0006_patient_avatar`, generando dos hojas; `0008_merge` las une (forma estándar y segura — NO renombrar migraciones ya aplicadas). `makemigrations --check` → "No changes detected": modelo y migraciones en sync. Al commitear, coordinar con la sesión del expediente para no duplicar/renumerar migraciones.

---

## 7. Pendientes / ideas a futuro

- Marcar ⭐/👑 también desde el **Expediente** (drawer de detalle), no solo desde la tarjeta.
- Asignar/quitar etiquetas custom también desde el Expediente (hoy solo desde el formulario de edición).
- "Mis favoritos" por usuario (si algún día se pide), como tabla aparte — el catálogo actual es siempre de toda la clínica (D-A).
- Paginación / scroll infinito cuando crezca el volumen de pacientes (hoy se muestra la primera página).
- Filtro combinado (p. ej. VIP + atendidos este mes): el selector ya soporta `segment` + `category_id` en combinación, pero la UI no expone todos los cruces todavía.
