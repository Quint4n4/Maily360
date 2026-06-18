/**
 * Validación de formato EN VIVO (solo UX / comodidad para el usuario).
 *
 * IMPORTANTE: el backend es la AUTORIDAD de la validación. Estas funciones
 * replican EXACTAMENTE los regex del backend (ni más estrictos ni más laxos)
 * para dar feedback inmediato; el backend vuelve a validar y devuelve 400 si
 * algo no cumple. Si un regex del backend cambia, hay que sincronizar aquí.
 *
 * Fuentes (backend = autoridad):
 *   - Teléfono / celular / WhatsApp:  apps/pacientes/views.py  _PHONE_RE
 *                                     apps/clinica/serializers.py _PHONE_RE
 *   - Código postal:                  apps/pacientes/views.py  postal_code RegexField
 *   - Email:                          serializers.EmailField (formato email estándar)
 *   - Redes (fb/ig/yt):               apps/clinica/serializers.py _validate_social_field
 *                                     (_HTML_TAG_RE + _CONTROL_CHAR_RE)
 *   - CURP:                           apps/pacientes/views.py   _CURP_RE (regex RENAPO)
 *
 * NOTA sobre CURP: el backend usa el patrón RENAPO
 *   ^[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z\d]\d$  (case-insensitive, se normaliza a
 *   mayúsculas). Es MÁS LAXO que un regex de CURP "completo" (no valida que las
 *   2 primeras vocales/consonantes ni el mes/día sean válidos). Replicamos el
 *   del backend porque el backend es la autoridad: validar de más rechazaría
 *   CURPs que el backend sí acepta.
 */

// ── Regex (copia EXACTA de los del backend) ─────────────────────────────────

/** Teléfono nacional o internacional, 7–20 caracteres. (_PHONE_RE) */
const TELEFONO_RE = /^\+?[\d\s\-()]{7,20}$/

/** Código postal: exactamente 5 dígitos. */
const CP_RE = /^\d{5}$/

/**
 * Email "estándar". DRF EmailField usa el validador de Django, que es bastante
 * permisivo. Usamos un patrón razonable y pragmático (parte local @ dominio con
 * TLD). El backend tiene la última palabra; esto solo evita errores obvios.
 */
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

/** Etiqueta HTML real: < seguido de letra, / o ! (sin espacio inmediato). (_HTML_TAG_RE) */
const HTML_TAG_RE = /<[a-zA-Z/!][^>]*>/

/** Carácter de control U+0000–U+001F. (_CONTROL_CHAR_RE) */
// eslint-disable-next-line no-control-regex
const CONTROL_CHAR_RE = /[\x00-\x1f]/

/** CURP — patrón RENAPO del backend (case-insensitive). (_CURP_RE) */
const CURP_RE = /^[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z\d]\d$/i

// ── Validadores de formato (true = válido) ──────────────────────────────────

/** ¿El teléfono/celular/WhatsApp tiene formato válido? */
export function esTelefonoValido(valor: string): boolean {
  return TELEFONO_RE.test(valor)
}

/** ¿El código postal son exactamente 5 dígitos? */
export function esCPValido(valor: string): boolean {
  return CP_RE.test(valor)
}

/** ¿El email tiene formato válido? */
export function esEmailValido(valor: string): boolean {
  return EMAIL_RE.test(valor)
}

/** ¿El valor está libre de etiquetas HTML y caracteres de control? (redes sociales) */
export function sinHTML(valor: string): boolean {
  return !HTML_TAG_RE.test(valor) && !CONTROL_CHAR_RE.test(valor)
}

/** ¿La CURP cumple el patrón RENAPO del backend? */
export function esCurpValido(valor: string): boolean {
  return CURP_RE.test(valor)
}

// ── Helper de UX: error de un campo opcional ────────────────────────────────

/**
 * Devuelve el mensaje de error de formato para un campo, o `null` si es válido.
 *
 * Regla de UX: un campo VACÍO nunca marca error de formato (la obligatoriedad
 * se maneja aparte). Solo se valida el formato cuando hay contenido.
 *
 * @param valor    contenido actual del campo
 * @param valido   función de validación de formato (p. ej. esTelefonoValido)
 * @param mensaje  texto a mostrar si el formato es inválido
 */
export function errorDeCampo(
  valor: string,
  valido: (v: string) => boolean,
  mensaje: string,
): string | null {
  const v = valor.trim()
  if (v === '') return null
  return valido(v) ? null : mensaje
}

// ── Mensajes estándar (reutilizables en todos los formularios) ──────────────

export const MSG = {
  telefono: 'Teléfono inválido',
  whatsapp: 'Número de WhatsApp inválido',
  cp: 'El código postal debe tener 5 dígitos',
  email: 'Correo electrónico inválido',
  html: 'No se permite HTML',
  curp: 'CURP inválida (formato RENAPO, 18 caracteres)',
} as const
