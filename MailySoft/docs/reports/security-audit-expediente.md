# Auditoría de seguridad — Expediente clínico (`apps/expediente` + frontend)

| Campo | Valor |
|---|---|
| Auditor | django-security + revisión de validación de frontend |
| Protocolo | [`PROTOCOLO-AUDITORIA-SEGURIDAD.md`](PROTOCOLO-AUDITORIA-SEGURIDAD.md) (3 fases) + checklist frontend |
| Commit auditado | main local (post `19dccd4`) — sin push a GitHub |
| Fecha | 2026-06-25 |
| Marco normativo | NOM-024 · NOM-004 · LFPDPPP · OWASP Django/DRF · COFEPRIS (cédula) |
| Veredicto final | ✅ Backend seguro (2 correcciones menores) · ⚠️ Frontend: faltan validaciones de campo (cédula y rangos de signos) |
| Estado | **Corregido en working tree el 2026-06-25 (sin commit). Backend 679 tests verdes; frontend `tsc`+`vite build` OK.** |

---

## Clasificación

El expediente clínico es el corazón de datos sensibles del sistema (diagnósticos, evolución, signos vitales, alergias). Datos de salud = categoría sensible LFPDPPP (protección máxima) + inmutabilidad NOM-004 + bitácora NOM-024. La cédula profesional del médico, además, va impresa en la receta COFEPRIS, por lo que su validez importa legalmente.

---

## A. Backend — Auditoría 3 fases (`apps/expediente`)

### Resultado por fase

- **Fase 1 (código/acceso):** LIMPIO. Cero secretos, cero SQLi, cero XSS. Todos los 16 endpoints con `permission_classes` declarativo (`HasClinicRole`, fail-closed); ninguno `AllowAny`. IDOR cubierto: todo detail endpoint usa selector con `TenantManager` → 404 para tenant ajeno. FK (patient/appointment/doctor/evolution) validadas con `tenant_id` en el service. Validación de entrada **exhaustiva** (ver controles positivos).
- **Fase 2 (multi-tenant/PII/inmutabilidad):** RLS **COMPLETA en las 8 tablas** (`ENABLE+FORCE+USING+WITH CHECK`). Inmutabilidad NOM-004 correcta (evoluciones/signos/addenda append-only, a nivel BD con `CheckConstraint` + sin rutas de mutación). Bitácora NOM-024 con 17 acciones, `resource_repr` siempre UUID (nunca PII). **2 hallazgos MEDIO** (abajo).
- **Fase 3 (config/deps del módulo):** Subida de imágenes (`EvolutionImage`) reutiliza `core/files.py` (Pillow real, whitelist JPG/PNG/WEBP, rechaza SVG, anti-bomba, nombre aleatorio, ruta por tenant, tope 20/nota). PDF del libro clínico con WeasyPrint + `_secure_fetcher` (solo `data:`, sin SSRF/LFI). Pendiente global Pillow CVE aplica (este módulo procesa imágenes de usuarios).

### Hallazgos backend

**🟡 MEDIO-1 — PII + texto clínico en notificación de enfermería** (`services.py:818-820`)
El `title` incluye `patient.full_name` y el `body` hasta 200 caracteres del texto clínico de las indicaciones. Si la tabla de notificaciones se filtrara, expone nombre + extracto médico juntos (LFPDPPP). Corrección: título/cuerpo genéricos + `target_id` (UUID) para navegar.

**🟡 MEDIO-2 — `all_objects` innecesario + comentario engañoso** (`services.py:1163`)
Único `all_objects` fuera de `apps/plataforma`. Es seguro (el tenant ya se validó antes), pero el comentario es incorrecto y puede invitar a copiar el patrón en un contexto peligroso. Cambiar a `EvolutionImage.objects.filter(evolution=evolution).count()`.

**🟢 INFO** — `TextField` sin `max_length` en el modelo (el límite sí está en los serializers, defensa en profundidad recomendada).

---

## B. Frontend — Validación de campos (lo que pidió el dueño)

> Principio: la validación del front es UX; **el backend es la autoridad**. Lo ideal es validar en AMBOS.

### Hallazgos de validación

**🟠 ALTO — Cédula profesional sin validación (front NI backend)** — *el hallazgo principal*
- `personal/MiembroDetalleDrawer.tsx:333` ("Cédula profesional"): `<input>` de texto libre — acepta letras, símbolos, longitud ilimitada.
- `consultorio/SeccionPerfilMedico.tsx:399` (número de credencial COFEPRIS) y `:118` (cédulas adicionales): igual, texto libre.
- Backend: `personal/models.py:62` solo tiene `max_length=30` sin `validate_`; el número de credencial (`clinica/serializers.py:499`) solo rechaza HTML + `max_length=60`. **Nadie exige "solo dígitos / máximo de dígitos".**
- Riesgo: una cédula inválida (con letras o longitud absurda) llega impresa en la **receta COFEPRIS**. Mitigante parcial: las credenciales pasan por validación humana del admin (D-21) antes de salir en receta — pero no hay guard de formato.
- Corrección: front `inputMode="numeric"` + filtro `replace(/\D/g,'')` + `maxLength` + regex; backend `RegexValidator(r'^\d{7,8}$')` (la cédula mexicana es de 7–8 dígitos — confirmar regla exacta con el dueño).

**🟡 MEDIO — Signos vitales sin rango en el front (la herramienta ya existe)**
- `VisitaSignos.tsx:160` y `SignosTab.tsx:280` usan `<input type="number">` (sí bloquean letras) pero **no aplican min/max** ni `errorDeSignoVital`.
- El proyecto YA tiene `VITAL_RANGES` y `errorDeSignoVital` en `src/lib/validacion.ts:130-157`, y `RecetasTab.tsx` los usa correctamente (patrón a imitar). El backend sí valida rangos (atrapa con 400), pero el front debería avisar antes.
- `SignosTab.tsx` además le falta `inputMode="decimal"`.

**🟢 INFO — Campos de texto sin `maxLength`** (diagnóstico, evolución SOAP, ~80 campos de historia clínica). Riesgo solo UX (el backend acota con `max_length`; el usuario recibiría 400 al pasarse).

### Controles positivos del frontend
- **Cero XSS**: ninguna ocurrencia de `dangerouslySetInnerHTML` en `src`.
- **Cliente HTTP central**: el único `fetch(` está en `src/lib/http.ts`; sin `fetch`/axios sueltos.
- **400 de DRF mapeado** a mensajes legibles (`apiErrors.ts`), no se muestra JSON crudo.
- Choices (severidad, tipo de diagnóstico, etc.) son `<select>` cerrados; fechas con `datetime-local`; imágenes con `accept` correcto.

---

## Resumen de hallazgos

| Área | 🔴 Crít. | 🟠 Alto | 🟡 Medio | 🟢 Info |
|---|---|---|---|---|
| Backend (3 fases) | 0 | 0 | 2 | 1 |
| Frontend (validación) | 0 | 1 (cédula) | 1 (signos) | 1 (maxLength) |

## Controles positivos verificados (backend)
RLS completa en las 8 tablas · inmutabilidad NOM-004 (BD + rutas) · bitácora NOM-024 (17 acciones, sin PII) · validación de rangos fisiológicos de signos vitales · choices cerrados · whitelist de claves JSON de HC · rechazo de campos desconocidos · fechas futuras bloqueadas · subida de imágenes con Pillow (la más completa del proyecto) · WeasyPrint sin SSRF · paginación con tope · regla del médico (D-EC-2) · evolución solo sobre cita ATTENDED.

## Estado de remediación (2026-06-25 — en working tree, sin commit)
1. ✅ **Cédula** validada en front (`MiembroDetalleDrawer.tsx`, `SeccionPerfilMedico.tsx`: solo dígitos, `inputMode="numeric"`) y backend (serializers de `personal` + `clinica`; regla "solo dígitos, opcional, sin tope fijo"). +15 tests.
2. ✅ `errorDeSignoVital` + `min`/`max` aplicados en `VisitaSignos.tsx` y `SignosTab.tsx` (reutilizando `VITAL_RANGES`).
3. ✅ Backend MEDIO-1: notificación de enfermería sin PII ni texto clínico.
4. ✅ Backend MEDIO-2: `all_objects` innecesario reemplazado por `objects` + comentario corregido.
5. 🟢 Pendiente opcional: `maxLength` en campos de texto del front (UX); `max_length` en `TextField` del modelo (defensa en profundidad).
- ⏳ Transversal (no de este módulo): actualizar **Pillow 10.4.0 → 12.2.0** (CVE).

Verificación: `pytest apps/personal apps/clinica apps/expediente` = **679 passed, 0 failed**; frontend `tsc -b` + `vite build` = OK.

## Veredicto
**Backend: ✅ seguro.** **Frontend: ✅ validaciones de cédula y rangos de signos implementadas el 2026-06-25** (working tree, sin commit). Los 2 medios de backend quedaron corregidos. Único pendiente de seguridad transversal: actualizar Pillow (CVE global). Ninguna falla permitía fuga cross-tenant ni toma de control.

## Referencias
NOM-024 · NOM-004 · LFPDPPP art. 3.VI · OWASP Django/DRF · ADR-0003 · D-21 (validación híbrida de credenciales).
