import { useState } from 'react'
import { Plus, MapPin, Pencil, Trash2, Loader2 } from 'lucide-react'
import Topbar from '../components/Topbar'
import NuevoConsultorioDrawer, { ConsultorioEdit } from '../components/personal/NuevoConsultorioDrawer'
import NuevoMiembroDrawer from '../components/personal/NuevoMiembroDrawer'
import EquipoTab from '../components/personal/EquipoTab'
import { useConsultoriosManage, useDeactivateConsultorio } from '../hooks/personal'
import type { Consultorio as ConsultorioApi } from '../types/personal'
import { useRole } from '../auth/RoleContext'
import { puedeEditar } from '../auth/permisos'

type Tab = 'equipo' | 'consultorios'
const TAB_LABEL: Record<Tab, string> = { equipo: 'Equipo', consultorios: 'Consultorios' }

export default function PersonalPage() {
  const { role } = useRole()
  const editar = puedeEditar(role, 'personal')
  const gestor = role === 'owner' || role === 'admin'

  const tabs: Tab[] = gestor ? ['equipo', 'consultorios'] : ['consultorios']
  const [tab, setTab]               = useState<Tab>(gestor ? 'equipo' : 'consultorios')
  const [nuevoConsul, setNuevoCons] = useState(false)
  const [nuevoMiembro, setNuevoMi]  = useState(false)
  const [editConsul, setEditConsul] = useState<ConsultorioEdit | null>(null)

  const consultoriosQ = useConsultoriosManage()
  const bajaConsul = useDeactivateConsultorio()
  const consultorios: ConsultorioApi[] = consultoriosQ.data?.results ?? []

  const editarConsultorio = (c: ConsultorioApi) =>
    setEditConsul({ id: c.id, name: c.name, location: c.location, color_hex: c.color_hex })

  const desactivarConsultorio = (c: ConsultorioApi) => {
    if (!window.confirm(`¿Desactivar el consultorio “${c.name}”? Dejará de aparecer en la agenda.`)) return
    bajaConsul.mutate(c.id)
  }

  const nuevoSegunTab = () => (tab === 'equipo' ? setNuevoMi(true) : setNuevoCons(true))
  const labelNuevo = tab === 'equipo' ? 'Nuevo miembro' : 'Nuevo consultorio'

  return (
    <div className="min-h-screen relative">

      {/* Fondo */}
      <div className="fixed inset-0 -z-10" style={{ background: 'linear-gradient(135deg, #b89a52 0%, #d8c690 45%, #f1e8cf 100%)' }} />
      <div className="fixed inset-0 -z-10 bg-cover bg-center" style={{ backgroundImage: "url('/fondo-agenda.jpg')" }} />
      <div className="fixed inset-0 -z-10" style={{ background: 'rgba(255,255,255,0.20)' }} />

      <Topbar active="personal" />

      <div className="p-5 max-w-[1300px] mx-auto">

        {/* ════ Cabecera + pestañas ════ */}
        <div className="glass-card rounded-2xl px-6 py-5">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">Personal</h1>
              <p className="text-sm text-gray-500">Equipo y consultorios de tu clínica</p>
            </div>
            {editar && (
              <button
                onClick={nuevoSegunTab}
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110"
                style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
              >
                <Plus className="w-4 h-4" /> {labelNuevo}
              </button>
            )}
          </div>

          {/* Pestañas */}
          <div className="flex gap-1.5 mt-4">
            {tabs.map(t => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className="px-5 py-2 rounded-xl text-sm font-medium transition-colors"
                style={tab === t
                  ? { background: '#C9A227', color: '#fff' }
                  : { background: 'rgba(255,255,255,0.6)', color: '#7A756C' }}
              >
                {TAB_LABEL[t]}
              </button>
            ))}
          </div>
        </div>

        {/* ════ Equipo (roles → miembros → ficha) ════ */}
        {tab === 'equipo' && <EquipoTab enabled={gestor} />}

        {/* ════ Consultorios ════ */}
        {tab === 'consultorios' && (
          <>
            {consultoriosQ.isLoading && (
              <div className="flex items-center justify-center gap-2 mt-16 text-amber-700">
                <Loader2 className="w-5 h-5 animate-spin" /> Cargando…
              </div>
            )}
            {consultoriosQ.isError && !consultoriosQ.isLoading && (
              <div className="glass-card rounded-2xl mt-5 py-10 text-center text-sm text-red-600">
                No se pudieron cargar los consultorios.
              </div>
            )}
            {!consultoriosQ.isLoading && !consultoriosQ.isError && (
              <div className="grid gap-4 mt-5" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}>
                {consultorios.map(c => {
                  const color = c.color_hex || '#C9A227'
                  return (
                    <div key={c.id} className="glass-card rounded-2xl p-5" style={{ opacity: c.is_active ? 1 : 0.6 }}>
                      <div className="flex items-start justify-between mb-4">
                        <div className="w-12 h-12 rounded-2xl shrink-0" style={{ background: color }} />
                        <span className={`badge ${c.is_active ? 'badge-success' : 'badge-neutral'}`}>
                          {c.is_active ? 'Activo' : 'Inactivo'}
                        </span>
                      </div>
                      <h3 className="text-base font-semibold text-gray-900">{c.name}</h3>
                      <div className="flex items-center gap-2 text-xs text-gray-600 mt-1.5">
                        <MapPin className="w-3.5 h-3.5 text-gray-400 shrink-0" /> {c.location || '—'}
                      </div>
                      <div className="flex items-center gap-2 mt-3 pt-3 border-t border-white/50">
                        <span className="w-3 h-3 rounded-full" style={{ background: color }} />
                        <span className="text-xs text-gray-500">Color en la agenda</span>
                      </div>

                      {editar && c.is_active && (
                        <div className="flex items-center gap-2 mt-4">
                          <button onClick={() => editarConsultorio(c)}
                            className="flex-1 inline-flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs font-semibold transition-colors hover:bg-amber-50"
                            style={{ color: '#B8860B', background: 'rgba(201,162,39,0.10)' }}>
                            <Pencil className="w-3.5 h-3.5" /> Editar
                          </button>
                          <button onClick={() => desactivarConsultorio(c)} disabled={bajaConsul.isPending}
                            className="inline-flex items-center justify-center gap-1.5 py-2 px-3 rounded-lg text-xs font-semibold text-red-600 transition-colors hover:bg-red-50 disabled:opacity-50"
                            style={{ background: 'rgba(192,57,43,0.08)' }}>
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      )}
                    </div>
                  )
                })}
                {consultorios.length === 0 && (
                  <div className="col-span-full glass-card rounded-2xl py-16 text-center text-sm text-gray-500">
                    Aún no hay consultorios. Crea el primero con “Nuevo consultorio”.
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>

      <NuevoMiembroDrawer open={nuevoMiembro} onClose={() => setNuevoMi(false)} />
      <NuevoConsultorioDrawer open={nuevoConsul} onClose={() => setNuevoCons(false)} />
      <NuevoConsultorioDrawer open={editConsul !== null} editing={editConsul} onClose={() => setEditConsul(null)} />
    </div>
  )
}
