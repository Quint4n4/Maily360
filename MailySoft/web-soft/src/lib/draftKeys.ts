/**
 * draftKeys — helpers para las claves de los BORRADORES LOCALES (localStorage).
 *
 * Un borrador local protege el avance de un formulario si el usuario recarga,
 * cierra por error o deja algo a medias. NO se guarda nada en el servidor; es
 * solo UX de resiliencia. La autoridad de los datos sigue siendo el backend.
 *
 * La clave incluye usuario + tenant + tipo de formulario + entidad para NO
 * mezclar borradores entre usuarios/clínicas/pacientes en el mismo navegador.
 *
 *   maily:draft:v1:{userId}:{tenantId}:{formType}:{entityId}
 */

/** Prefijo común de todas las claves de borrador (para el barrido en logout). */
const DRAFT_PREFIX = 'maily:draft:'

/** Versión del esquema del borrador; subir si cambia la forma del payload. */
const DRAFT_VERSION = 'v1'

/** Tipos de formulario que soportan borrador local. */
export type DraftFormType =
  | 'historia'
  | 'evolucion'
  | 'calendarizacion'
  | 'resumen'
  | 'plan_integral'

/**
 * Arma la clave de un borrador. `entityId` identifica la entidad concreta
 * (paciente, plan, evolución…) para no pisar borradores de otras.
 */
export function draftKey(
  userId: string,
  tenantId: string,
  formType: DraftFormType,
  entityId: string,
): string {
  return `${DRAFT_PREFIX}${DRAFT_VERSION}:${userId}:${tenantId}:${formType}:${entityId}`
}

/**
 * Elimina TODAS las claves de borrador del navegador. Se llama en el logout
 * para no dejar datos clínicos de borradores en el equipo tras cerrar sesión.
 * Defensivo: si localStorage no está disponible, no rompe nada.
 */
export function clearAllDrafts(): void {
  if (typeof window === 'undefined') return
  try {
    const keys: string[] = []
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)
      if (k && k.startsWith(DRAFT_PREFIX)) keys.push(k)
    }
    for (const k of keys) localStorage.removeItem(k)
  } catch {
    // Modo privado / cuota / storage deshabilitado: ignorar en silencio.
  }
}
