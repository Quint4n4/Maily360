# Fase B1 — Recetas médicas

> Parte de la **Fase B** del expediente (documentos y soporte). Ref. legacy: `expediente-clinico-analisis-legacy.md` §3.6 y §5.
> Estado: **IMPLEMENTADO** — B1.1–B1.4 completas (2026-06-19); formatos, estilos, dos versiones y validación de credenciales completas (2026-06-23).
> Para el detalle de formatos configurables, estilos de fondo, validación híbrida de credenciales y plan de fases: ver [`recetas-formatos-plan.md`](recetas-formatos-plan.md).

## 1. Qué replica del legacy

La pantalla "Recetas" del legacy: **buscador de medicamento** (catálogo) + cuerpo + **Recomendaciones** + **Tratamiento** (lista de medicamentos con indicación) + **"Copia Recomendación/Tratamiento"** (reusar de una receta previa) + **"Mostrar Signos"** (snapshot de la última toma) + Imprimir / **PDF** / WhatsApp / Historial. El legacy permite editar/eliminar → **lo cambiamos** (ver DR-1).

## 2. Decisiones (tomadas con el dueño, 2026-06-18)

- **DR-1 — Inmutable + anular con motivo.** La receta NO se edita ni se borra una vez creada (documento médico-legal, NOM-004; consistente con `EvolutionNote`). Si hay un error → se **anula** (baja lógica con motivo, queda en historial) y se emite una nueva. Para corregir cómodo: **"copiar de una receta previa"** (precarga recomendaciones + medicamentos en una receta nueva).
- **DR-2 — Catálogo precargado (global) + custom por tenant + texto libre.** Se precarga un catálogo base de medicamentos comunes (global, compartido). Cada clínica puede agregar los suyos (custom). Siempre se permite texto libre como respaldo.
- **DR-3 — PDF con membrete.** Se genera PDF (WeasyPrint, HTML→PDF) usando el membrete y datos de `ClinicSettings` (Mi Consultorio) + datos del médico (`Doctor`: sello, cédula, cédulas adicionales, `recipe_use_responsible_doctor`).
- **DR-4 — WhatsApp simulado** por ahora (igual que el resto de Fase B).
- **DR-5 — No borrado físico** de información clínica (consistente con Fase A).
- **DR-6 — Permisos:** el **médico** crea y anula recetas; lectura = roles clínicos (recepción/finanzas NO ven recetas). El médico solo emite recetas a su nombre (o se valida `doctor_get_for_user`).
- **DR-7 — Snapshot/autocontenida.** El `PrescriptionItem` **congela** el nombre y presentación del medicamento al crear (no FK obligatoria al catálogo). La receta **congela** los signos vitales en JSON. Así la receta inmutable no depende de cambios futuros del catálogo ni de signos.

## 3. Modelos (app nueva `apps/recetas`)

- **`GlobalMedication(BaseModel)`** — catálogo global (sin tenant). `generic_name`, `commercial_name` (opcional), `form` (choices: tableta/cápsula/jarabe/suspensión/solución/crema/inyectable/…), `concentration` (ej. "500 mg"), `presentation` (ej. "caja con 20"), `is_active`. RLS: legible por todos (`tenant_id IS NULL`-style: tabla global, sin política por tenant); escritura solo seed/plataforma.
- **`Medication(TenantAwareModel)`** — medicamentos custom de la clínica (autocompletado del médico). Mismos campos clínicos + `created_by`. RLS normal por tenant.
- **`Prescription(TenantAwareModel)`** — receta. `patient` (FK), `doctor` (FK personal), `appointment` (FK opcional), `evolution_note` (FK opcional), `folio` (consecutivo por tenant), `issued_at`, `recommendations` (texto), `vitals_snapshot` (JSON, nullable — snapshot de la última toma), `status` (`active`/`cancelled`), `cancelled_at`, `cancelled_by`, `cancellation_reason`. **Inmutable** (sin update de contenido; solo anular).
- **`PrescriptionItem(TenantAwareModel)`** — renglón de tratamiento. `prescription` (FK), `order`, `medication_name` (snapshot, requerido), `medication_presentation` (snapshot), `global_medication`/`medication` (FK opcional, solo trazabilidad), `indication` (texto: dosis/cómo tomarlo, requerido), `quantity` (opcional).

## 4. Endpoints (`api/v1/`)

- `recetas/medicamentos/buscar/?q=` — `GET` autocompletar (une global + custom del tenant).
- `recetas/medicamentos/` — `POST` crear medicamento custom (médico).
- `expediente/<patient_id>/recetas/` — `GET` historial del paciente / `POST` crear (acepta `copy_from=<id>` para precargar de una previa).
- `recetas/<prescription_id>/` — `GET` detalle.
- `recetas/<prescription_id>/anular/` — `POST` anular con `reason`.
- `recetas/<prescription_id>/pdf/` — `GET` descargar PDF con membrete.

Bitácora (NOM-024): `PRESCRIPTION_CREATE/READ/CANCEL`, `PRESCRIPTION_PDF`, `MEDICATION_CREATE`.

## 5. Sub-fases (flujo: django-engineer → django-security → fixes → verificación propia)

- **B1.1 — Catálogo de medicamentos.** Modelos `GlobalMedication` + `Medication`, RLS, **seed** de medicamentos comunes (data migration / management command), endpoint de búsqueda + alta custom, permisos, bitácora.
- **B1.2 — Recetas.** `Prescription` + `PrescriptionItem` (crear inmutable, anular con motivo, historial por paciente, detalle, copiar-de-previa, snapshot de signos), permisos, bitácora.
- **B1.3 — PDF con membrete.** WeasyPrint + template HTML; usa `ClinicSettings` + `Doctor`; endpoint de descarga.
- **B1.4 — Frontend.** Sección **Recetas** en el expediente (ExpedienteDrawer): crear receta (buscador con autocompletar, renglones de tratamiento, recomendaciones, "mostrar signos", "copiar de previa"), historial, ver/descargar PDF, anular, WhatsApp simulado.
