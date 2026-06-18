import { Loader2, Pencil, Trash2 } from 'lucide-react'
import { useAppointmentTypesManage, useDeactivateAppointmentType } from '../../hooks/agenda'
import type { AppointmentType } from '../../types/agenda'
import type { TipoCitaEdit } from './NuevoTipoCitaDrawer'
import { useConfirm } from '../common/DialogProvider'

interface Props {
  editar: boolean
  onEditar: (t: TipoCitaEdit) => void
}

export default function TiposCitaTab({ editar, onEditar }: Props) {
  const { data: tipos, isLoading, isError } = useAppointmentTypesManage()
  const baja = useDeactivateAppointmentType()
  const confirmar = useConfirm()

  const desactivar = async (t: AppointmentType) => {
    if (!(await confirmar({ titulo: 'Desactivar tipo de cita', mensaje: `¿Desactivar el tipo de cita “${t.name}”? Dejará de aparecer al agendar.`, peligro: true, textoConfirmar: 'Desactivar' }))) return
    baja.mutate(t.id)
  }

  if (isLoading) {
    return <div className="flex items-center justify-center gap-2 mt-16 text-amber-700"><Loader2 className="w-5 h-5 animate-spin" /> Cargando…</div>
  }
  if (isError) {
    return <div className="glass-card rounded-2xl mt-5 py-10 text-center text-sm text-red-600">No se pudieron cargar los tipos de cita.</div>
  }

  const lista = tipos ?? []

  return (
    <div className="grid gap-4 mt-5" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}>
      {lista.map(t => {
        const color = t.color_hex || '#9A958C'
        return (
          <div key={t.id} className="glass-card rounded-2xl p-5" style={{ opacity: t.is_active ? 1 : 0.6, borderLeft: `4px solid ${color}` }}>
            <div className="flex items-start justify-between mb-3">
              <div className="w-12 h-12 rounded-2xl shrink-0" style={{ background: color }} />
              <span className={`badge ${t.is_active ? 'badge-success' : 'badge-neutral'}`}>{t.is_active ? 'Activo' : 'Inactivo'}</span>
            </div>
            <h3 className="text-base font-semibold text-gray-900">{t.name}</h3>
            <div className="flex items-center gap-2 mt-3 pt-3 border-t border-white/50">
              <span className="w-3 h-3 rounded-full" style={{ background: color }} />
              <span className="text-xs text-gray-500">Color en la agenda</span>
            </div>

            {editar && t.is_active && (
              <div className="flex items-center gap-2 mt-4">
                <button onClick={() => onEditar({ id: t.id, name: t.name, color_hex: t.color_hex })}
                  className="flex-1 inline-flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs font-semibold transition-colors hover:bg-amber-50"
                  style={{ color: '#B8860B', background: 'rgba(201,162,39,0.10)' }}>
                  <Pencil className="w-3.5 h-3.5" /> Editar
                </button>
                <button onClick={() => desactivar(t)} disabled={baja.isPending}
                  className="inline-flex items-center justify-center gap-1.5 py-2 px-3 rounded-lg text-xs font-semibold text-red-600 transition-colors hover:bg-red-50 disabled:opacity-50"
                  style={{ background: 'rgba(192,57,43,0.08)' }}>
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            )}
          </div>
        )
      })}
      {lista.length === 0 && (
        <div className="col-span-full glass-card rounded-2xl py-16 text-center text-sm text-gray-500">
          Aún no hay tipos de cita. Crea el primero con “Nuevo tipo”.
        </div>
      )}
    </div>
  )
}
