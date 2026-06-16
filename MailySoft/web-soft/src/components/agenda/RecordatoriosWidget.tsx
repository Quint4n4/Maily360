import { Bell, Check, Loader2 } from 'lucide-react'
import { useReminders, useToggleNoteDone } from '../../hooks/notas'
import { dayRangeUTC, localHHMM12 } from '../../lib/fecha'

interface Props {
  /** Día seleccionado en la agenda (yyyy-mm-dd local). */
  dayKey: string
}

/** Recordatorios personales del usuario logueado para el día seleccionado.
 *  Privado: el backend solo devuelve las notas visibles para este usuario. */
export default function RecordatoriosWidget({ dayKey }: Props) {
  const { from, to } = dayRangeUTC(dayKey)
  const { data, isLoading } = useReminders({ date_from: from, date_to: to })
  const toggle = useToggleNoteDone()

  const recordatorios = [...(data?.results ?? [])].sort((a, b) => (a.remind_at ?? '').localeCompare(b.remind_at ?? ''))

  return (
    <div className="glass-card rounded-2xl overflow-hidden">
      <div className="flex items-center justify-between px-5 py-3 border-b border-white/40">
        <span className="text-sm font-semibold text-gray-700 flex items-center gap-2">
          <Bell className="w-4 h-4" style={{ color: '#C9A227' }} /> Mis recordatorios
        </span>
        {recordatorios.length > 0 && (
          <span className="text-[11px] font-bold px-2 py-0.5 rounded-full" style={{ background: 'rgba(201,162,39,0.15)', color: '#B8860B' }}>
            {recordatorios.length}
          </span>
        )}
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center gap-2 py-6 text-amber-700 text-sm"><Loader2 className="w-4 h-4 animate-spin" /> Cargando…</div>
      ) : recordatorios.length === 0 ? (
        <p className="px-5 py-6 text-center text-xs text-gray-400 italic">Sin recordatorios para este día.</p>
      ) : (
        <div className="max-h-[280px] overflow-y-auto">
          {recordatorios.map((n, i) => {
            const hecha = n.is_task && n.done
            return (
              <div key={n.id} className="flex items-start gap-2.5 px-5 py-3" style={{ borderTop: i > 0 ? '1px solid rgba(255,255,255,0.45)' : 'none' }}>
                {n.is_task ? (
                  <button onClick={() => toggle.mutate(n.id)} title={hecha ? 'Marcar pendiente' : 'Marcar hecha'}
                    className="mt-0.5 w-4 h-4 rounded shrink-0 flex items-center justify-center transition-colors"
                    style={{ border: '2px solid #C9A227', background: hecha ? '#C9A227' : 'transparent' }}>
                    {hecha && <Check className="w-2.5 h-2.5 text-white" />}
                  </button>
                ) : (
                  <span className="mt-1.5 w-2 h-2 rounded-full shrink-0" style={{ background: '#C9A227' }} />
                )}
                <div className="min-w-0 flex-1">
                  <p className={`text-sm font-medium leading-tight truncate ${hecha ? 'line-through text-gray-400' : 'text-gray-800'}`}>
                    {n.title || (n.is_task ? 'Tarea' : 'Nota')}
                  </p>
                  <p className="text-[11px] text-gray-500 mt-0.5">{localHHMM12(n.remind_at!)}{n.scope !== 'personal' ? ' · aviso' : ''}</p>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
