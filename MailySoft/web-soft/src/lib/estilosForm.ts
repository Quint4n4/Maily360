/**
 * Estilos compartidos de formularios (clases Tailwind reutilizadas por los
 * modales de agenda y notas). Antes el mismo string estaba copiado en cada
 * componente; ahora vive aquí como fuente única.
 */

/** Input "glass" estándar: fondo translúcido, borde claro, foco ámbar. */
export const INPUT =
  'w-full rounded-xl border border-white/60 bg-white/70 px-4 py-2.5 text-base sm:text-sm text-gray-800 outline-none focus:border-amber-500 focus:ring-2 focus:ring-amber-500/20'

/** Etiqueta (label) que va encima de un campo del formulario. */
export const LABEL = 'block text-xs font-medium text-gray-500 mb-1'
