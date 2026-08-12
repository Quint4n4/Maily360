# docs/_legacy — Documentación archivada

> **Nada de esto se borró.** Es la documentación previa de Maily360 que ya no describe el sistema de
> hoy. Se conserva porque sirve para entender **por qué** se tomaron decisiones que hoy no se
> explican solas, y porque la brecha entre lo que se planeó y lo que se construyó es información.
>
> Archivado el **2026-08-11**, en la sesión A1 de adopción del modelo de trabajo
> (`ADOPCION-PROYECTO-EXISTENTE.md`). Lo vigente quedó consolidado en `docs/01-analisis.md`.
>
> **Regla:** ningún agente debe usar un documento de esta carpeta como fuente de verdad. Si un
> documento de aquí contradice al código, gana el código. Si contradice a `docs/01-analisis.md`,
> gana el análisis.

---

## Criterio de archivado

Se archivó lo que cumple una de estas tres condiciones:

1. **El código lo contradice.** Afirma cosas que hoy son falsas.
2. **Es la bitácora de un trabajo ya cerrado.** Fue correcto en su momento; ya no es especificación
   viva.
3. **Quedó consolidado** en `docs/01-analisis.md`, y mantener las dos copias garantiza que en tres
   meses una de las dos esté mal.

Se **dejó vivo** todo lo que sigue siendo especificación o procedimiento ejecutable: los tres ADR,
`DECISIONES-CLAVE.md`, el protocolo de auditoría de seguridad, el reporte de métricas y
escalabilidad, las guías de despliegue, y los documentos de diseño que todavía describen algo no
terminado.

---

## Qué hay aquí y por qué se archivó

### Estado del proyecto

| Documento | Por qué se archivó |
|---|---|
| `ESTADO-DEL-PROYECTO.md` | Fechado 2026-06-25; después vinieron **112 commits** con features grandes que no aparecen (sucursales, planes y entitlements, app `pdfs`, portal de plataforma conectado, horario de agenda configurable, rediseño del expediente). Su lista de pendientes daba por abiertas ocho cosas ya cerradas. Consolidado en `docs/01-analisis.md`. |

### Sucursales / multi-sede

| Documento | Por qué se archivó |
|---|---|
| `design/sucursales-plan-implementacion.md` | Plan ejecutado (fases 1-4 en el código). Además ubica el helper de sucursal en `apps/core` — vive en `apps/clinica/sucursal_scope.py` — y promete un `sucursal_default` en `/me` que no existe. |
| `design/sucursales-hallazgos-seguridad.md` | Auditoría cerrada: los clústeres B a G están corregidos y verificados en el código. Su veredicto "NO DESPLEGAR" ya no aplica. El único hallazgo que dejó abierto (el detalle de nota de cita sin acotar por sede) se rescató a `01-analisis.md §9`. |

> Siguen vivos `design/sucursales-arquitectura-analisis.md` (única fuente de la matriz
> compartido-vs-por-sede), `design/sucursales-mapa-apps.md` y `design/sucursales-guia-de-pruebas.md`.

### Planes, módulos y entitlements

| Documento | Por qué se archivó |
|---|---|
| `design/planes-modulos-entitlements-analisis.md` | **Obsoleto.** Su sección "estado real del código verificado" está desmentida punto por punto: decía que no había gating por plan en ningún endpoint (hoy hay 91 vistas con guard) y que multi-sucursal no se podía apagar (hoy es el límite `max_sucursales`). El empaquetado que propone (Individual / Consultorio / Multi-sede / Enterprise) nunca se implementó. |
| `design/planes-modulos-mapa-dependencias.md` | El mapa vivo es `backend/apps/core/modules.py`. Lista 13 módulos donde hay 12, inventa un módulo de "avisos internos", omite `calendarizacion` y cita modelos `TreatmentScheme` que no existen (son `TreatmentPlan`). |
| `design/planes-entitlements-plan-implementacion.md` | Bitácora del trabajo terminado; en producción desde 2026-07-27. Su tabla de empaquetado aprobado se rescató a `01-analisis.md §5`, porque hasta hoy la única fuente de esa verdad era el comando `seed_planes`. |

### Portal interno de Maily

| Documento | Por qué se archivó |
|---|---|
| `design/plataforma-portal.md` | Superado por el código: documenta 6 endpoints donde hay 17, y da por maqueta las pantallas de Suscripciones y Sistema, que ya consumen datos reales. Sus secciones de roles de plataforma y seguridad cross-tenant merecen convertirse en un ADR corto. |
| `design/plataforma-fases-plan.md` | Bitácora de las fases 0-5, todas cerradas. Su sección "lo que NO existe todavía" es hoy falsa en los cinco puntos. |

### Expediente clínico

| Documento | Por qué se archivó |
|---|---|
| `design/expediente-clinico-analisis-legacy.md` | Insumo de requisitos del sistema PHP heredado, ya consumido. Cuatro piezas que propone **no se construyeron** y son backlog de producto: estudios de laboratorio con archivos, documentos del expediente, consentimiento informado y catálogo formal CIE-10. |
| `design/libro-clinico-plan.md` | Implementado por completo, pese a que su encabezado sigue diciendo "plan". Describe el PDF como síncrono dentro del request; hoy es asíncrono con Celery. |

> Siguen vivos `design/expediente-clinico-plan.md` (única fuente escrita de las decisiones
> D-EC-1…D-EC-9, aún codificadas) y `design/expediente-saas-rediseno.md` (sus fases 3 y 4 son el
> backlog de monetización por especialidad).

### PDFs

| Documento | Por qué se archivó |
|---|---|
| `design/pdfs-unificacion-diseno.md` | Se autodeclara "propuesta"; las tres fases están implementadas. Habla de "los 4 PDFs del sistema"; hoy hay 7 tipos registrados. |
| `design/pdf-async-celery-plan.md` | Implementado. Decidía una cola Celery dedicada para PDFs que finalmente no se creó — el worker es único y sin `-Q`. Ese detalle quedó anotado como pendiente de infraestructura. |

### Frontend y roles

| Documento | Por qué se archivó |
|---|---|
| `design/plan-paneles-roles.md` | **Obsoleto y engañoso.** Su matriz de roles contradice al código en tres celdas (enfermería sí edita pacientes; el médico sí lee personal y sí cotiza), y describe `web-platform/` como una app aparte con su propio login: esa carpeta quedó vacía y el portal vive dentro de `web-soft`. |
| `design/frontend-integracion-backend.md` | Plan cumplido. Su diagnóstico de partida ("todo usa datos mock", "el rol está hardcodeado") ya no aplica. Su decisión de tokens híbridos merece un ADR si no lo tiene. |
| `design/frontend-mvp-prototipado.md` | El documento más viejo del repo. La mayoría de las pantallas que nombra no existen con ese nombre ni esa forma: no hay dashboard, no hay sidebar, "Pacientes" es `ContactosPage`. Se conserva por la paleta de marca. |

### Reportes de fase y auditorías cerradas

Bitácoras de trabajo terminado. Se archivan completas; **los pendientes que seguían abiertos ya se
rescataron** a `docs/01-analisis.md §9`.

| Documento | Nota |
|---|---|
| `reports/fase-1-cimientos.md` | Cierre 2026-06-02. |
| `reports/fase-3-agenda.md` | Cierre 2026-06-03. |
| `reports/fase-4-permisos-y-auditoria.md` | Su lista "falta para certificación formal" sigue abierta: exportación firmada de la bitácora, retención y particionado automáticos, elección explícita de clínica. |
| `reports/review-paso-2.md` | Tres nits triviales aún abiertos. |
| `reports/review-paso-3.md` | Cerrado sin pendientes. |
| `reports/security-audit-paso-2.md` | Hallazgos corregidos. Queda abierto un INFO: `normalize_email` no baja todo el correo a minúsculas. |
| `reports/security-audit-paso-3.md` | Los 17 hallazgos cerrados. Sus dos pendientes de `MetaWhatsAppAdapter` siguen latentes porque el adaptador no existe. |
| `reports/security-audit-expediente.md` | Todo corregido y ya commiteado, pese a que el documento dice "en working tree sin commit". |
| `reports/sesion-finanzas-cotizaciones-pdfs.md` | Pendientes vivos: timbrado CFDI real, plan de pagos diferido, consentimiento LFPDPPP para la analítica RFM. |

> Siguen vivos en `docs/reports/`: **`PROTOCOLO-AUDITORIA-SEGURIDAD.md`** (procedimiento repetible,
> con comandos ejecutables) y **`metricas-refactor-huerfanos-escalabilidad.md`** (backlog vivo de
> rendimiento con sus checkmarks al día).

---

## Documentos que quedaron vivos, con correcciones pendientes

Nada de esto se archivó, pero cada uno afirma algo que el código desmiente. Corregirlos es trabajo
de una sesión corta; hasta entonces, léelos con esta lista al lado.

| Documento vivo | Qué corregir |
|---|---|
| `README.md` (raíz de MailySoft) | Describe el proyecto del primer día: dice que ambos frontends están "pendientes" y anuncia Django 5.1 (real: 5.2.15). No enlaza la documentación que el equipo usa. **Reescribir.** |
| `CHANGELOG.md` (raíz del repo) | Se detuvo siete semanas antes del último commit y el orden interno está roto. Le falta todo: expediente, recetas, finanzas, sucursales, entitlements, portal, deploy. |
| `docs/adr/0001-stack-y-arquitectura.md` | Especialidades como apps-plugin (nunca existieron; se resolvió con planes y módulos), Master Patient Index (no existe), WebSockets (dependencia muerta), frontend "por definir" (ya decidido). |
| `docs/adr/0002-arquitectura-multi-tenant.md` | Tres de sus cinco capas cambiaron: el manager ahora falla seguro (`qs.none()`), el resolutor principal es `TenantAPIView` y no el middleware, y el GUC tiene modo configurable. `X-Tenant-ID` sigue sin implementarse. |
| `docs/adr/0003-...-shared-rls.md` | Vigente y hoy más cierto que cuando se escribió. Añadir el rol de aplicación NOSUPERUSER, sin el cual `FORCE RLS` no aplica al dueño de las tablas. |
| `docs/DECISIONES-CLAVE.md` | Fechado 2026-06-23. Le faltan las decisiones de sucursales, planes y entitlements, y PDFs asíncronos. D-12 (especialidades como plugins) quedó superada. |
| `docs/DEPLOY-RAILWAY.md` | No documenta `MIGRATION_DATABASE_URL`, `DB_TENANT_GUC_MODE` ni las variables de Sentry, todas leídas en producción. Falta `seed_planes` en el paso de siembra, o la clínica nace sin catálogo de planes. Y contradice a otro documento sobre el nombre del proyecto en Railway. |
| `docs/reports/PROTOCOLO-AUDITORIA-SEGURIDAD.md` | Dos avisos fechados ya falsos: la brecha de RLS de cuatro tablas está cerrada, y los CVE de Pillow y `xlsx` también. |
| `docs/design/agenda-modelo-datos.md` | La máquina de estados sí permite `Agendada → En sala` (walk-in); la configuración de agenda tiene tres campos más (horario y duración de slot); `AgendaBlock` ya no es "v2"; `series_id` sí se usa; la política RLS ya lleva `WITH CHECK`. |
| `docs/design/multi-citas-disponibilidad.md` | Borrar el pendiente de "slots fijos 9:00–17:30": ya vienen de la configuración de la clínica. |
| `docs/design/recetas-plan.md` | El endpoint de PDF ya no devuelve el archivo: devuelve 202 con un job. `PrescriptionItem` tiene nueve campos más de los documentados. |
| `docs/design/recetas-formatos-plan.md` | No existe un campo `paper` (se deriva del layout); la whitelist de `sections` tiene 10 claves, no 5; hay 2 templates en uso, no 3. |
| `docs/design/expediente-clinico-plan.md` | Documenta 6 modelos y 8 endpoints; hoy hay 15 modelos y 34 rutas. La fase D (`SpecialtyModule`/`TenantModule`) nunca se construyó así. |
| `docs/design/notas-y-tareas-plan.md` | D-D es falsa: los avisos dirigidos a un rol ya no son exclusivos del dueño. Faltan los campos `is_important` y `sucursal`. |
| `docs/design/notificaciones-plan.md` | Hay 7 tipos de notificación, no 4, y 5 tipos de destino, no 4. |
| `docs/design/audit-modelo-datos.md` | La bitácora es **solo del dueño**, no de dueño y administrador. El catálogo de acciones pasó de ~20 a más de 100. |
| `docs/design/cotizaciones-plan.md` | Su encabezado dice "propuesta": está implementado. Solo lectura **sí** puede consultar cotizaciones. |
| `docs/design/finanzas-pacientes-unificacion-plan.md` | Marcar qué fases se ejecutaron y qué modelos se descartaron (`Adjustment`, `PaymentPlan`, `PatientFinancialSnapshot`, `ServiceFeeSchedule` no existen; el RFM se calcula en vivo). El CFDI ya no es manual. |
| `docs/design/frontend-security-testing.md` | El ítem "localStorage MVP vs cookie httpOnly" ya está resuelto: memoria + cookie `httpOnly`. |
| `docs/design/pgbouncer-rls-escalabilidad.md` | El cálculo de hilos de gunicorn: son 6 por defecto (3 workers × 2 threads), no 8. |
| `docs/design/e2e-playwright.md` | Habla de 3 planes; hay 5 (4 activos). Falta `seed_planes` en los prerrequisitos. |
| `docs/design/sucursales-arquitectura-analisis.md` | Borrar la cabecera "no hay código aún". Cinco desviaciones: `Sucursal` vive en `clinica` y no en `tenancy`; los catálogos de servicios y paquetes **sí** llevan sede; `Note` **sí** lleva sede; el CFDI tiene FK propia de sede; la bitácora quedó solo del dueño y sin campo de sede. |

---

## La carpeta `documentacion/` de la raíz del repo

**No se tocó**, y no es documentación técnica: son maquetas, presentaciones comerciales y material
de análisis del sistema heredado, en HTML. Contiene información de negocio que **no existe en
ningún `.md`** y que vale rescatar antes de darla por muerta:

- `modelo_venta_infraestructura.html` — el flujo de venta, el tiering de almacenamiento y **el costo
  de infraestructura por clínica**. Es lo más valioso: la economía del producto no está escrita en
  ningún otro lado.
- `historias_de_usuario_mvp.html` — las únicas historias de usuario del proyecto.
- `unificacion_maily_te_cuida.html` y `maqueta_maily_te_cuida.html` — el plan y la maqueta de la app
  del paciente, que no existe en el código.
- `index.html` — el business case del sistema PHP heredado, con costos de desarrollo y operación.
- `maqueta_compra_fisioterapia.html` — el flujo de **compra en autoservicio**, que tampoco existe.

⚠ **Los precios de estos HTML ($13,990, $22,990, $199/mes, $399/mes) no coinciden con los del
código ($1,500 / $4,500 / $8,900 MXN al mes). Hay que fijar una sola lista antes de vender la
siguiente licencia.**
