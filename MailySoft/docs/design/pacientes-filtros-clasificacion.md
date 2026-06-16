# Pacientes — filtros por visita + clientes potenciales + favoritos/VIP

> Implementado durante el sprint de **2026-06-16**.
> Estado: **IMPLEMENTADO** (backend + frontend). Frontend compila; backend con **526 tests en verde (87 nuevos)**, cobertura: selectors 98%, serializers 100%, views 94%.
> Backend: `apps/pacientes` (modelo, selector `patient_list`, service `patient_set_classification`, endpoint `/clasificacion/`) + `apps/agenda` (`Appointment.reschedule_count`).
> Frontend: `web-soft` (página `ContactosPage`, hooks/api/tipos de paciente, reutiliza `MiniCalendario`).

---

## 1. Objetivo

Hacer el área de Pacientes mucho más útil para el día a día de la clínica:

1. **Filtrar la lista** por cuándo se atendió al paciente: Recientes, Esta semana, Este mes, o un **rango personalizado de fechas** (con mini-calendarios).
2. Un apartado **"Clientes potenciales"**: gente que mostró interés (agendó y luego canceló o reagendó) pero **nunca llegó a atenderse** — para darles seguimiento comercial.
3. Marcar pacientes como **⭐ Favorito** y **👑 VIP** para tenerlos visibles y darles seguimiento preferente.

---

## 2. Decisiones tomadas (locked)

- **D-A · Favoritos y VIP son de TODA la clínica.** Dos booleanos en el paciente (`is_favorite`, `is_vip`), no por usuario. Lo que marca recepción lo ven médicos y dueño. Si en el futuro se quiere "mis favoritos" por usuario, sería una tabla aparte (cambio mayor).
- **D-B · "Visto" = cita ATENDIDA.** El "último visto" de un paciente se deriva de su cita con `status=attended` más reciente (`last_seen`). No se desnormaliza ningún campo: se calcula con anotaciones en el selector (siempre exacto). Aprovecha el índice `appt_patient_hist_idx`.
- **D-C · "Esta semana" = semana CALENDARIO (lunes–domingo)** en la zona horaria de la clínica (`America/Mexico_City`). Confirmado con el dueño 2026-06-16: NO es una ventana móvil de "últimos 7 días". Consecuencia esperada: a inicios de semana el apartado puede salir vacío si nadie se ha atendido aún esos días (no es bug).
- **D-D · "Clientes potenciales" = 0 citas atendidas Y (canceló O reagendó).** Para detectar "reagendó" se agregó `Appointment.reschedule_count` (contador que sube en cada reagendamiento). Un paciente que ya tiene UNA cita atendida **no** es potencial, aunque también haya cancelado.
- **D-E · "Por fecha" = rango entre dos fechas** (date_from, date_to), ambas requeridas, `date_to` inclusive. Se eligen con dos mini-calendarios (Desde / Hasta).
- **D-F · Disponibilidad de datos siempre anotada.** El selector anota `last_seen`, `attended_count`, `cancelled_count`, `rescheduled_count` SIEMPRE, para que el serializer los exponga sin romper el endpoint de detalle (usa `getattr` tolerante).

---

## 3. Backend

### 3.1 Modelos
- `Patient` (`apps/pacientes/models.py`): `is_favorite` y `is_vip` (`BooleanField(default=False, db_index=True)`).
- `Appointment` (`apps/agenda/models.py`): `reschedule_count = PositiveSmallIntegerField(default=0)`.
- `appointment_reschedule` ahora hace `reschedule_count += 1` en cada reagendamiento (incluido cuando reactiva una cancelada). `appointment_reactivate` (mismo horario) **no** lo incrementa.

### 3.2 Selector — `patient_list`
`patient_list(*, search="", segment="all", date_from=None, date_to=None) -> QuerySet[Patient]`

Anota siempre: `last_seen`, `attended_count`, `cancelled_count`, `rescheduled_count`. Segmentos:

| `segment` | Regla | Orden |
|---|---|---|
| `all` | todos los activos | -created_at |
| `recent` | con `last_seen` no nulo | -last_seen |
| `week` | atendidos en la semana calendario actual | -last_seen |
| `month` | atendidos en el mes calendario actual | -last_seen |
| `date` | atendidos entre `date_from` y `date_to` (inclusive) | -last_seen |
| `potential` | `attended_count=0` Y (`cancelled_count>0` O `rescheduled_count>0`) | -created_at |
| `favorites` | `is_favorite=True` | -created_at |
| `vip` | `is_vip=True` | -created_at |

Los filtros temporales usan `Exists(Appointment.objects.filter(...))` para no multiplicar filas por JOIN. Los límites de semana/mes/rango se calculan en la zona local del proyecto y se convierten a UTC (helpers `_week_bounds`, `_month_bounds`, `_date_range_bounds`).

### 3.3 Service + endpoint de clasificación
- `patient_set_classification(*, patient, user, is_favorite=None, is_vip=None) -> Patient`: solo cambia los flags no-None; si ambos None, no toca BD; registra auditoría `PATIENT_UPDATE`.
- `POST /api/v1/pacientes/<uuid>/clasificacion/` body `{is_favorite?, is_vip?}` → 200 con el paciente. Permiso `PatientPermission` (owner/admin/doctor/nurse/reception; readonly NO).

### 3.4 Endpoint de lista (ampliado)
`GET /api/v1/pacientes/?segment=&date_from=&date_to=&search=`. Si `segment=date` sin ambas fechas → 400. El output ahora incluye `is_favorite`, `is_vip`, `last_seen_at`, `attended_count`.

### 3.5 Migraciones
- `pacientes/0007_patient_is_favorite_is_vip.py`
- `agenda/0010_appointment_reschedule_count.py`
- `pacientes/0008_merge_20260616_1224.py` — merge para resolver dos hojas `0006` (`0006_patient_avatar` y `0006_patient_nom004_fields`). ⚠️ Ver §6.

### 3.6 Tests
87 tests nuevos en `apps/pacientes/tests/test_segmentos_selectors.py` (41), `test_clasificacion_services.py` (13), `test_clasificacion_api.py` (23) y `apps/agenda/tests/test_reschedule_count.py` (10). Cubren cada segmento, bordes inclusivos del rango, la regla de "potencial", aislamiento multi-tenant y el conteo de reagendamientos. **526 total, 0 fallos.**

---

## 4. Frontend (`web-soft`)

- **Tipos** (`types/paciente.ts`): `PatientOut` gana `is_favorite`, `is_vip`, `last_seen_at`, `attended_count`. Nuevo `PatientSegment` y `PatientClassifyInput`.
- **API** (`api/pacientes.ts`): `listPatients` acepta `segment`/`date_from`/`date_to`; nuevo `setPatientClassification`.
- **Hooks** (`hooks/pacientes.ts`): `usePatients({search, segment, dateFrom, dateTo})` (con `enabled` que espera ambas fechas en modo rango); `useSetPatientClassification`.
- **UI** (`pages/ContactosPage.tsx`):
  - **Barra de chips** dorados: Todos · Recientes · Esta semana · Este mes · 📅 Por fecha · Clientes potenciales · ⭐ Favoritos · 👑 VIP.
  - El chip **📅 Por fecha** despliega dos `MiniCalendario` (Desde / Hasta); el "Hasta" usa `min=dateFrom`.
  - En cada tarjeta: botón **⭐ favorito** y **👑 VIP** (toggle directo, overlay fuera del botón del cuerpo para no abrir el expediente), **borde dorado** en las VIP, y **"Última: <fecha real>"** (de `last_seen_at`) o "Sin citas atendidas".
  - Mensaje de vacío a la medida de cada segmento.
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
- "Mis favoritos" por usuario (si algún día se pide), como tabla aparte.
- Paginación / scroll infinito cuando crezca el volumen de pacientes (hoy se muestra la primera página).
- Posible filtro combinado (p. ej. VIP + atendidos este mes).
