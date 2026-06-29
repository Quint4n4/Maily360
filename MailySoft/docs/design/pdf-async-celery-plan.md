# Plan — Generación de PDFs en segundo plano (Celery)

> 2026-06-29 · Resuelve el riesgo **P0** del reporte de métricas:
> *"PDF (WeasyPrint) síncrono bloquea workers"*.
>
> ✅ **IMPLEMENTADO para RECETAS (2026-06-29):** modelo `PrescriptionPdfJob` + RLS,
> servicio (encolar + caché), tarea Celery (`generate_prescription_pdf`), 3 endpoints
> (GET encolar → status → file) y frontend (`VisorPdf` vía encolar+polling+descargar).
> Tarea en la **cola default** (la cola `pdf` dedicada queda como optimización de prod).
> **Pendiente:** aplicar el mismo patrón al **libro clínico** (`expediente`).

## 1. El problema (en una línea)

Hoy, generar un PDF (libro clínico o receta) corre **WeasyPrint dentro del request HTTP**,
bloqueando un worker de Gunicorn 5–10 segundos. Con solo ~8 hilos, varias descargas
simultáneas **congelan toda la API** para el resto de usuarios.

**Dónde está hoy (síncrono):**
- `apps/expediente/views_libro.py:240` → `libro_pdf_build(...)` dentro del `GET`.
- `apps/recetas/views.py:436` → `prescription_pdf_build(...)` dentro del `GET`.
- El frontend lo consume con `VisorPdf.tsx` (`cargar()` → fetch del PDF como **blob** con Bearer).
- Los modelos **NO guardan** el PDF: se regenera en cada descarga.

**Lo que ya existe a favor:**
- Celery configurado (broker + result backend en Redis) — `config/settings/base.py:231`.
- Patrón de tarea con contexto de tenant — `apps/agenda/tasks.py`.
- Storage en S3 en prod (`django-storages`) — `config/settings/production.py:98`.

## 2. La solución

Mover WeasyPrint a una **tarea de Celery** (worker aparte). La API encola y responde
al instante; el PDF se genera en 2º plano, se **guarda** (S3/disco) y el frontend lo
descarga cuando está listo.

## 3. Decisiones tomadas (2026-06-29)

| # | Decisión | Elegido |
|---|---|---|
| D1 | ¿Cómo sabe el front que el PDF está listo? | ✅ **Polling** (el front pregunta cada ~2 s). |
| D2 | ¿Se cachea el PDF generado? | ✅ **Sí.** Recetas inmutables → caché perfecto. |
| D3 | ¿Por dónde empezar? | ✅ **Recetas primero**, luego el libro clínico. |
| D4 | ¿Cola dedicada de Celery? | ✅ **Sí**, cola `pdf`. |

## 4. Plan por fases

### Fase 0 — Infra Celery (cola dedicada)
- Definir cola `pdf` (`task_routes` en la config de Celery).
- Worker que consuma `pdf` (mismo contenedor o uno aparte en `docker-compose.yml`).

### Fase 1 — Backend: modelo de "trabajo de PDF" + tarea
- Modelo `PdfJob` (multi-tenant): `status` (pending/done/failed), `kind` (prescription/book),
  `params` (id + formato/modo), `file` (FileField → S3), `created_by`, timestamps.
- Tarea `generate_pdf(job_id)`:
  1. Setea el contexto de tenant (como `agenda/tasks.py`).
  2. Corre `prescription_pdf_build` / `libro_pdf_build`.
  3. Guarda el PDF en `PdfJob.file` y marca `status=done`.
  4. En error → `status=failed` + log (NUNCA tumba nada).
- **Idempotencia + caché (D2):** antes de encolar, si ya hay un `PdfJob` `done` para los
  mismos `params` (receta inmutable), se reusa.

### Fase 2 — Backend: endpoints asíncronos
- `POST /.../pdf/` → encola (o reusa caché) y devuelve **202** + `{ job_id, status }`.
- `GET /.../pdf/<job_id>/` → `{ status }` si pending; el **archivo** (o URL) si done; 404/410 si falla.
- Permisos idénticos a los actuales (anti-IDOR por tenant).

### Fase 3 — Frontend: `VisorPdf` con polling
- Cambiar `cargar()`: 1) `POST` para encolar → `job_id`; 2) `GET` cada ~2 s hasta `done`;
  3) descargar el blob y mostrarlo. Mensaje "Generando PDF…" mientras espera.
- Sin cambios visibles para el usuario salvo el spinner los primeros segundos.

### Fase 4 — Verificación
- Tests backend: tarea genera y guarda; endpoint 202→done; caché reusa; aislamiento por tenant.
- Prueba de carga manual: varias descargas simultáneas **no** congelan la API.
- El usuario prueba el flujo en el navegador (ver/descargar receta y libro).

## 5. En qué ayuda (beneficios)

1. **La app deja de congelarse** cuando varios descargan PDFs a la vez.
2. **Escala**: aguanta más usuarios concurrentes sin tumbar la API.
3. **Más rápido a la segunda**: con caché, re-descargar una receta es instantáneo.
4. **Robusto**: si WeasyPrint falla, no rompe el request; se marca `failed` y se reintenta.

## 6. Alcance / esfuerzo estimado
- Fase 0–2 (backend): ~1–1.5 días. Fase 3 (frontend): ~medio día. Fase 4: ~medio día.
- Riesgo: **medio** — cambia el contrato del endpoint de PDF; el frontend (`VisorPdf`)
  es el único consumidor, lo que acota el impacto.
