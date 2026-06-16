import { useState, type ReactNode } from 'react'
import { ChevronLeft, ChevronRight, X } from 'lucide-react'
import { toDayKey, fromDayKey, addMonths } from '../../lib/fecha'

const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
const DOW = ['L', 'M', 'M', 'J', 'V', 'S', 'D']

interface Props {
  /** Día seleccionado ('yyyy-mm-dd') o null. */
  value: string | null
  /** Si se provee, los días son clicables (modo edición). Sin él = solo lectura. */
  onPick?: (date: string) => void
  /** Botón × para quitar este calendario. */
  onRemove?: () => void
  /** Día mínimo seleccionable ('yyyy-mm-dd'). Los anteriores se ven apagados. */
  min?: string
  /** Acento del día elegido: 'gold' (editable) | 'green' (preview) | 'red' (ocupado). */
  accent?: 'gold' | 'green' | 'red'
  /** Contenido bajo el calendario (p. ej. la hora o un input de hora). */
  footer?: ReactNode
}

/** Calendario mensual chiquito: navega meses y (opcional) elige un día. */
export default function MiniCalendario({ value, onPick, onRemove, min, accent = 'gold', footer }: Props) {
  const [cursor, setCursor] = useState<Date>(() => (value ? fromDayKey(value) : new Date()))

  const y = cursor.getFullYear()
  const mIdx = cursor.getMonth()
  const startDow = (new Date(y, mIdx, 1).getDay() + 6) % 7 // Lunes = 0
  const dias = new Date(y, mIdx + 1, 0).getDate()
  const selBg = accent === 'green' ? '#3B6D11' : accent === 'red' ? '#C0392B' : '#C9A227'

  const celdas: (number | null)[] = []
  for (let i = 0; i < startDow; i++) celdas.push(null)
  for (let d = 1; d <= dias; d++) celdas.push(d)

  return (
    <div className="relative rounded-2xl p-2.5" style={{ background: 'rgba(255,255,255,0.85)', border: '1px solid rgba(0,0,0,0.07)' }}>
      {onRemove && (
        <button type="button" onClick={onRemove} title="Quitar esta cita"
          className="absolute top-1 right-1 w-6 h-6 rounded-full flex items-center justify-center text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors z-10">
          <X className="w-3.5 h-3.5" />
        </button>
      )}

      <div className="flex items-center justify-between mb-1.5" style={{ paddingLeft: 2, paddingRight: onRemove ? 26 : 2 }}>
        <button type="button" onClick={() => setCursor(c => addMonths(c, -1))} className="text-gray-400 hover:text-gray-700 transition-colors shrink-0"><ChevronLeft className="w-4 h-4" /></button>
        <span className="text-xs font-semibold text-gray-700 capitalize">{MESES[mIdx]} {y}</span>
        <button type="button" onClick={() => setCursor(c => addMonths(c, 1))} className="text-gray-400 hover:text-gray-700 transition-colors shrink-0"><ChevronRight className="w-4 h-4" /></button>
      </div>

      <div className="grid grid-cols-7 gap-0.5">
        {DOW.map((d, i) => <span key={i} className="text-[10px] text-center text-gray-400 font-medium py-0.5">{d}</span>)}
        {celdas.map((d, i) => {
          if (d === null) return <span key={i} />
          const key = toDayKey(new Date(y, mIdx, d))
          const sel = value === key
          const deshab = min ? key < min : false
          const clicable = !!onPick && !deshab
          return (
            <button key={i} type="button" disabled={!clicable}
              onClick={clicable ? () => onPick!(key) : undefined}
              className="text-[11px] text-center py-1 rounded-full transition-colors"
              style={sel
                ? { background: selBg, color: '#fff', fontWeight: 600 }
                : { color: deshab ? '#D1CFC9' : '#3A352C', background: 'transparent', cursor: clicable ? 'pointer' : 'default' }}>
              {d}
            </button>
          )
        })}
      </div>

      {footer && <div className="mt-2">{footer}</div>}
    </div>
  )
}
