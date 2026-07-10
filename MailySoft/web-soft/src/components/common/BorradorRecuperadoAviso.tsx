/**
 * BorradorRecuperadoAviso — barra discreta que avisa que se recuperó un
 * BORRADOR LOCAL sin guardar (localStorage) al reabrir un formulario.
 *
 * Muestra desde cuándo es el borrador (hora relativa) y un botón "Descartar"
 * que borra el borrador local y revierte el formulario al estado del servidor.
 * Estilo sutil, en el lenguaje visual oro+blanco del expediente.
 */

import { History, X } from 'lucide-react'

const ORO_OSCURO = '#854F0B'

/** ISO-8601 → texto relativo en español ("hace 5 min", "ayer"…). */
function horaRelativa(iso: string): string {
  const fecha = new Date(iso)
  const ms = fecha.getTime()
  if (Number.isNaN(ms)) return ''
  const diffSeg = Math.round((Date.now() - ms) / 1000)
  if (diffSeg < 45) return 'hace unos segundos'
  const min = Math.round(diffSeg / 60)
  if (min < 60) return `hace ${min} min`
  const horas = Math.round(min / 60)
  if (horas < 24) return `hace ${horas} h`
  const dias = Math.round(horas / 24)
  if (dias === 1) return 'ayer'
  if (dias < 7) return `hace ${dias} días`
  // Más de una semana: fecha corta local.
  return fecha.toLocaleDateString('es-MX', { day: '2-digit', month: 'short' })
}

interface BorradorRecuperadoAvisoProps {
  /** Momento en que se guardó el borrador (ISO-8601). */
  savedAt: string
  /** Descarta el borrador y revierte el formulario al estado del servidor. */
  onDescartar: () => void
}

export default function BorradorRecuperadoAviso({
  savedAt, onDescartar,
}: BorradorRecuperadoAvisoProps) {
  return (
    <div
      className="flex items-center gap-2.5 rounded-xl px-3.5 py-2.5 text-sm"
      style={{ background: 'rgba(201,162,39,0.10)', border: '1px solid rgba(201,162,39,0.30)' }}
      role="status"
    >
      <History className="w-4 h-4 shrink-0" style={{ color: ORO_OSCURO }} />
      <span className="flex-1 min-w-0" style={{ color: '#6B5A1E' }}>
        Recuperamos tu borrador sin guardar
        <span className="text-amber-700/70"> · {horaRelativa(savedAt)}</span>
      </span>
      <button
        type="button"
        onClick={onDescartar}
        className="inline-flex items-center gap-1 shrink-0 px-2.5 py-1 rounded-lg text-xs font-semibold transition-colors hover:bg-black/5"
        style={{ color: ORO_OSCURO, border: '1px solid rgba(201,162,39,0.35)' }}
      >
        <X className="w-3.5 h-3.5" /> Descartar
      </button>
    </div>
  )
}
