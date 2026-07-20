# Resumen de sesión — Finanzas, Cotizaciones y unificación de PDFs

> Fecha: 2026-06-26 · Alcance: módulo de finanzas ligado al expediente, módulo de
> cotizaciones, unificación visual de todos los PDFs y visor inline. Todo en `main`
> y subido a GitHub (`Quint4n4/Maily360`).

## Resumen ejecutivo
Se construyó la unificación de **finanzas con el expediente del paciente** (estado de cuenta,
reportes, analítica de retención), un **módulo de cotizaciones** de cabecera, se **unificó la
identidad visual de los 4 PDFs** bajo el diseño de recetas y se agregó **vista previa inline**
de PDF en todo el sistema. Base de mercado: benchmark de DrChrono/Dentrix/Jane/SimplePractice
(ver `docs/design/finanzas-pacientes-unificacion-plan.md`). 2,346 tests backend en verde.

---

## 1. Finanzas unificada al expediente (3 fases)
Plan: `docs/design/finanzas-pacientes-unificacion-plan.md`.

- **Fase 1 — Estado de cuenta en el expediente** (`5d98bed`):
  `ClinicSettings.doctors_see_costs` (flag por clínica, migración `clinica/0010`); permisos
  `PatientStatementPermission`/`ChargeListPermission` (el médico ve el estado de cuenta solo si
  la clínica activa el flag); `charge_list` filtra por `?appointment=`. Front: badge de saldo en
  el expediente, pestaña "Estado de cuenta" (ledger + `PagoModal`), bloque de cuenta por visita
  en el libro.
- **Fase 2 — Reportes financieros** (`6fafba2`): `finance_period_report` + `finance_daily_sheet`
  (producción vs cobranza, collection %, **A/R aging** 0-30/31-60/61-90/90+, comparativa con
  periodo anterior, por método/servicio/doctor, ticket); endpoints `/finanzas/reporte/`,
  `/reporte/pdf/`, `/cierre-diario/`. Front: tab Reportes (KPIs + gráficas recharts), cierre
  diario imprimible, exportar PDF/Excel. **`xlsx`→`exceljs`** (CVE).
- **Fase 3 — Analítica de clientes RFM** (`884a3cf`): `apps/finanzas/retention.py` (RFM en vivo,
  segmentos nuevo/vip/frecuente/en_riesgo/perdido); endpoint `/finanzas/retencion/` (distribución
  + listas accionables + métricas retención/ticket/no-show/% próxima cita). **Solo visualización**
  (sin campañas automáticas).

**Ajustes UX posteriores:**
- Tarjetas del dashboard **clickeables** → llevan al detalle (`13cc6d7`).
- Estado de cuenta con vista **"Por cargo"** (estado Pagado/Parcial/Pendiente) (`880004f`).
- **Auto-asignación de pagos en cascada** (el pago baja la deuda solo) (`9b10629`).
- **Sin saldo a favor**: el pago no puede exceder la deuda; estado de cuenta con una sola métrica
  de deuda (`18d0008`); saldo en **rojo** (debe) / **verde** (al corriente) (`7e72a27`).
- **Panel "Servicios y precios"** en Mi Consultorio (catálogo CRUD de `ServiceConcept`) (`af89803`).

**Decisiones clave:** visibilidad de costos configurable por clínica; ledger derivado (sin tabla);
CFDI manual fuera de alcance; retención solo visualización; privacidad LFPDPPP pendiente para F3.

## 2. Cotizaciones (módulo top-level) — `59aa49b`
Plan: `docs/design/cotizaciones-plan.md`. El "motor" `Quote`/`QuoteItem` ya existía; se sacó a la
**barra superior** (`CotizacionesPage`), se conectó al **catálogo de servicios** (precio
automático), se agregó **PDF** y el **vínculo con la cita** (`Appointment.quote`, migración
`agenda/0011`): al agendar se elige la cotización aceptada y se ve en el detalle de la cita.
**Roles:** owner/admin/doctor/reception (el doctor cierra venta en consulta; finanzas/enfermería
fuera). Permiso `QuotePermission`.

## 3. Unificación visual de PDFs + visor
Plan: `docs/design/pdfs-unificacion-diseno.md`.
- **Base común `apps/core/pdf/`** (`7052de0`): helpers (`secure_fetcher`, imágenes),
  `build_brand_context`, parciales `clinic_header.html` + `brand_background.html` (ondas + marca de
  agua). Aplicado a libro clínico, reporte y cotización (encabezado + color + ondas).
- **Color de marca desde el FORMATO DE RECETA** (`6ac5de8`): `build_brand_context` toma el
  `accent_color` del formato de receta default del tenant (fallback `ClinicSettings.brand_color`
  → `#9A7B1E`), para que TODOS los PDFs usen el mismo color que la receta. Fix de márgenes: el
  `.page-bg` cubre la hoja física (top/left negativos) para que las ondas no se desborden.
- **Visor de PDF inline** (`dd7a27e`, `328e024`): componente `web-soft/src/components/VisorPdf.tsx`
  (modal con `<iframe>` + descargar dentro), montado con **portal a `document.body`** + z-index
  alto (evita que el expediente se le encime). Conectado en recetas, libro, reporte, cotización
  (tab + detalle de cita) y estado de cuenta.

## 4. Estado git
Todo en `main` y subido a GitHub (push `da95f2c..328e024`, fast-forward). La sesión de
expediente subió luego cédula/signos (`e85a365`) + el fix del test de auditoría aislado por tenant
(`f008a4a`). **Verificación final: 2,346 tests backend verdes, `tsc -b` limpio, migraciones
consistentes, sin marcadores de conflicto.**

## 5. Pendientes
- Refactor de **huérfanos/escalabilidad** (N+1 en expediente, índice `pg_trgm` en pacientes,
  borrado de componentes viejos de `personal/`): en progreso en otra sesión, aún sin commitear.
- Finanzas: timbrado **CFDI real** con PAC; **plan de pagos diferido** formal; consentimiento
  **LFPDPPP** para la analítica de retención. `xlsx` ya reemplazado por `exceljs`.
- Probar todos los flujos en `:5173` con el color de marca real de cada clínica.
