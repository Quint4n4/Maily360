import type { CredentialValidationStatus } from '../../types/credenciales'

/** Estilos por estado de validación de una credencial. */
const ESTILOS: Record<CredentialValidationStatus, { bg: string; color: string; label: string }> = {
  validada: { bg: 'rgba(46,125,91,0.14)', color: '#2E7D5B', label: 'Validada' },
  pendiente: { bg: 'rgba(201,162,39,0.18)', color: '#9A7B1E', label: 'Pendiente de validación' },
  rechazada: { bg: 'rgba(190,40,40,0.12)', color: '#B22222', label: 'Rechazada' },
}

/** Chip con el estado de validación de una credencial (validada/pendiente/rechazada). */
export default function CredencialEstadoBadge({
  status,
  label,
}: {
  status: CredentialValidationStatus
  /** Texto a mostrar (por defecto el del estado). */
  label?: string
}) {
  const e = ESTILOS[status] ?? ESTILOS.pendiente
  return (
    <span
      className="inline-flex items-center text-[10px] rounded-full px-1.5 py-0.5 whitespace-nowrap"
      style={{ background: e.bg, color: e.color }}
    >
      {label ?? e.label}
    </span>
  )
}
