import { useState } from 'react'
import { X, Loader2, AlertCircle, Users, HeartPulse, CalendarDays, Clock, Layers, SlidersHorizontal } from 'lucide-react'
import { useClinicaDetail, useSetClinicaEstado } from '../../hooks/plataforma'
import { ESTADO_CLINICA } from '../../data/clinicas'
import { formatFechaCorta, formatMesAnio } from '../../lib/fecha'
import type { ClinicaDetail } from '../../types/plataforma'
import { useConfirm } from '../common/DialogProvider'
import { MODULO_LABEL } from '../../lib/modulos'
import AjustesClinicaModal from './AjustesClinicaModal'

interface Props {
  clinicaId: string | null
  /** Si el rol puede suspender/reactivar (super_admin/sales). */
  puedeEditar: boolean
  onClose: () => void
}

export default function ClinicaDetailDrawer({ clinicaId, puedeEditar, onClose }: Props) {
  const { data, isLoading, isError } = useClinicaDetail(clinicaId)
  const cambiarEstado = useSetClinicaEstado()
  const confirmar = useConfirm()
  const [ajustesAbierto, setAjustesAbierto] = useState(false)

  if (!clinicaId) return null

  const toggleEstado = async (c: ClinicaDetail) => {
    const suspender = c.status !== 'suspended'
    if (suspender && !(await confirmar({
      titulo: 'Suspender clínica',
      mensaje: `¿Suspender a "${c.name}"? Quedará bloqueada hasta reactivarla.`,
      peligro: true,
      textoConfirmar: 'Suspender',
    }))) return
    cambiarEstado.mutate({ id: c.id, status: suspender ? 'suspended' : 'active' })
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end" style={{ background: 'rgba(30,22,8,0.4)', backdropFilter: 'blur(3px)' }} onClick={onClose}>
      <div className="h-full w-full max-w-md overflow-y-auto p-6" onClick={e => e.stopPropagation()}
        style={{ background: 'rgba(252,250,244,0.97)', backdropFilter: 'blur(20px)', boxShadow: '-12px 0 40px rgba(60,42,12,0.2)' }}>

        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-bold text-gray-900">Ficha de la clínica</h2>
          <button onClick={onClose} className="w-8 h-8 rounded-full flex items-center justify-center text-gray-400 hover:text-gray-700 hover:bg-black/5 transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {isLoading && (
          <div className="flex items-center justify-center gap-2 py-20 text-amber-700">
            <Loader2 className="w-5 h-5 animate-spin" /> Cargando ficha…
          </div>
        )}
        {isError && (
          <div className="flex items-center gap-2 py-10 text-red-600">
            <AlertCircle className="w-5 h-5 shrink-0" /> No se pudo cargar la ficha.
          </div>
        )}

        {data && (
          <>
            {/* Encabezado */}
            <div className="glass-card rounded-2xl p-5 mb-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="text-xl font-bold text-gray-900 truncate">{data.name}</h3>
                  <p className="text-xs text-gray-400">{data.slug}</p>
                </div>
                <span className={`badge ${ESTADO_CLINICA[data.status].badge} shrink-0`}>{ESTADO_CLINICA[data.status].label}</span>
              </div>
              <div className="mt-3 pt-3 border-t border-white/50 space-y-1.5 text-xs text-gray-500">
                <p>Alta: <span className="text-gray-700 font-medium">{formatMesAnio(data.created_at)}</span></p>
                {data.status === 'trial' && data.trial_ends_at && (
                  <p>Prueba termina: <span className="text-gray-700 font-medium">{formatFechaCorta(data.trial_ends_at)}</span></p>
                )}
                <p className="flex items-center gap-1.5">
                  <Clock className="w-3.5 h-3.5 text-gray-400" />
                  Última actividad: <span className="text-gray-700 font-medium">{data.ultima_actividad ? formatFechaCorta(data.ultima_actividad) : 'Sin actividad'}</span>
                </p>
              </div>
            </div>

            {/* Uso */}
            <div className="grid grid-cols-3 gap-3 mb-4">
              {[
                { icon: Users, label: 'Usuarios', valor: data.member_count, color: '#7E57C2' },
                { icon: HeartPulse, label: 'Pacientes', valor: data.patient_count, color: '#3A6EA5' },
                { icon: CalendarDays, label: 'Citas', valor: data.appointment_count, color: '#2E7D5B' },
              ].map(({ icon: Icon, label, valor, color }) => (
                <div key={label} className="glass-card rounded-2xl p-3 text-center">
                  <Icon className="w-4 h-4 mx-auto mb-1" style={{ color }} />
                  <p className="text-lg font-bold text-gray-900">{(valor ?? 0).toLocaleString('es-MX')}</p>
                  <p className="text-[10px] text-gray-400">{label}</p>
                </div>
              ))}
            </div>

            {/* Plan y ajustes (Fase 6) */}
            {data.entitlements && (
              <div className="glass-card rounded-2xl overflow-hidden mb-4">
                <div className="px-4 py-3 border-b border-white/50 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Layers className="w-4 h-4" style={{ color: '#C9A227' }} />
                    <h4 className="text-sm font-semibold text-gray-800">
                      Plan {data.entitlements.plan_name || '— sin plan'}
                    </h4>
                  </div>
                  {puedeEditar && (
                    <button onClick={() => setAjustesAbierto(true)}
                      className="inline-flex items-center gap-1.5 text-xs font-semibold" style={{ color: '#9A7B1E' }}>
                      <SlidersHorizontal className="w-3.5 h-3.5" /> Ajustar
                    </button>
                  )}
                </div>
                <div className="px-4 py-3">
                  {/* Consumo vs límite: detecta upsell de un vistazo */}
                  <div className="grid grid-cols-3 gap-2 mb-3">
                    {([
                      ['Usuarios', data.entitlements.usuarios],
                      ['Consultorios', data.entitlements.consultorios],
                      ['Sucursales', data.entitlements.sucursales],
                    ] as const).map(([label, c]) => {
                      const tope = c.limite
                      const lleno = tope !== null && c.actual >= tope
                      return (
                        <div key={label} className="text-center">
                          <p className="text-sm font-bold" style={{ color: lleno ? '#C0392B' : '#2A241B' }}>
                            {c.actual}<span className="text-gray-400 font-normal">/{tope ?? '∞'}</span>
                          </p>
                          <p className="text-[10px] text-gray-400">{label}</p>
                        </div>
                      )
                    })}
                  </div>
                  {/* Módulos encendidos */}
                  <div className="flex flex-wrap gap-1">
                    {data.entitlements.modules.map(m => (
                      <span key={m} className="text-[10px] px-1.5 py-0.5 rounded-full"
                        style={{ background: 'rgba(201,162,39,0.12)', color: '#854F0B' }}>
                        {MODULO_LABEL[m]}
                      </span>
                    ))}
                  </div>
                  {data.entitlements.override.notes && (
                    <p className="text-[10px] text-gray-400 mt-2 italic">
                      Ajuste: {data.entitlements.override.notes}
                    </p>
                  )}
                </div>
              </div>
            )}

            {/* Miembros */}
            <div className="glass-card rounded-2xl overflow-hidden mb-4">
              <div className="px-4 py-3 border-b border-white/50">
                <h4 className="text-sm font-semibold text-gray-800">Equipo ({data.members.length})</h4>
              </div>
              {data.members.length === 0 ? (
                <p className="px-4 py-6 text-center text-xs text-gray-400">Sin miembros.</p>
              ) : (
                data.members.map(m => (
                  <div key={m.id} className="flex items-center justify-between px-4 py-2.5 border-b border-white/30">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-800 truncate">{m.full_name || m.email}</p>
                      <p className="text-xs text-gray-400 truncate">{m.email}</p>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-[11px] font-medium px-2 py-0.5 rounded-full" style={{ background: 'rgba(201,162,39,0.14)', color: '#B8860B' }}>{m.role_display}</span>
                      {!m.is_active && <span className="badge badge-neutral">Inactivo</span>}
                    </div>
                  </div>
                ))
              )}
            </div>

            {/* Acción */}
            {puedeEditar && (
              data.status === 'suspended' ? (
                <button onClick={() => toggleEstado(data)} disabled={cambiarEstado.isPending}
                  className="w-full py-2.5 rounded-xl text-sm font-semibold text-white disabled:opacity-60" style={{ background: '#2E9E5B' }}>
                  Reactivar clínica
                </button>
              ) : (
                <button onClick={() => toggleEstado(data)} disabled={cambiarEstado.isPending}
                  className="w-full py-2.5 rounded-xl text-sm font-semibold disabled:opacity-60" style={{ background: '#FDE8E8', color: '#C0392B' }}>
                  Suspender clínica
                </button>
              )
            )}
          </>
        )}
      </div>

      {ajustesAbierto && data?.entitlements && (
        <AjustesClinicaModal
          tenantId={data.id}
          clinicaNombre={data.name}
          entitlements={data.entitlements}
          onClose={() => setAjustesAbierto(false)}
        />
      )}
    </div>
  )
}
