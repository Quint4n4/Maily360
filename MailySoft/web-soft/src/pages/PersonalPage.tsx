import { useState } from 'react'
import { Plus, Clock, Fingerprint, MapPin, Pencil, Trash2, Loader2 } from 'lucide-react'
import Topbar from '../components/Topbar'
import DoctorDetalleDrawer from '../components/personal/DoctorDetalleDrawer'
import NuevoDoctorDrawer from '../components/personal/NuevoDoctorDrawer'
import NuevoConsultorioDrawer, { ConsultorioEdit } from '../components/personal/NuevoConsultorioDrawer'
import { Doctor, initialesDoctor } from '../data/personal'
import { useDoctorsManage, useConsultoriosManage, useDeactivateConsultorio } from '../hooks/personal'
import type { Consultorio as ConsultorioApi } from '../types/personal'
import { useRole } from '../auth/RoleContext'
import { puedeEditar } from '../auth/permisos'

type Tab = 'doctores' | 'consultorios'

export default function PersonalPage() {
  const [tab, setTab]               = useState<Tab>('doctores')
  const [doctorSel, setDoctorSel]   = useState<Doctor | null>(null)
  const [nuevoDoctor, setNuevoDoc]  = useState(false)
  const [nuevoConsul, setNuevoCons] = useState(false)
  const [editConsul, setEditConsul] = useState<ConsultorioEdit | null>(null)
  const { role } = useRole()
  const editar = puedeEditar(role, 'personal')

  const doctoresQ = useDoctorsManage()
  const consultoriosQ = useConsultoriosManage()
  const bajaConsul = useDeactivateConsultorio()

  // Mapear doctores reales al shape que consumen las tarjetas y el drawer.
  const doctores: Doctor[] = (doctoresQ.data?.results ?? []).map(d => ({
    id: d.id,
    nombre: d.full_name,
    email: d.user_email,
    especialidad: d.specialty,
    cedula: d.cedula_profesional,
    duracion: d.default_appointment_duration,
    bio: d.bio_short,
    activo: d.is_active,
  }))
  const consultorios: ConsultorioApi[] = consultoriosQ.data?.results ?? []

  const cargando = tab === 'doctores' ? doctoresQ.isLoading : consultoriosQ.isLoading
  const conError = tab === 'doctores' ? doctoresQ.isError : consultoriosQ.isError

  const editarConsultorio = (c: ConsultorioApi) => {
    setEditConsul({ id: c.id, name: c.name, location: c.location, color_hex: c.color_hex })
  }

  const desactivarConsultorio = (c: ConsultorioApi) => {
    if (!window.confirm(`¿Desactivar el consultorio “${c.name}”? Dejará de aparecer en la agenda.`)) return
    bajaConsul.mutate(c.id)
  }

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
              <p className="text-sm text-gray-500">Doctores, consultorios y horarios de tu clínica</p>
            </div>
            {editar && (
              <button
                onClick={() => tab === 'doctores' ? setNuevoDoc(true) : setNuevoCons(true)}
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110"
                style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
              >
                <Plus className="w-4 h-4" /> {tab === 'doctores' ? 'Nuevo doctor' : 'Nuevo consultorio'}
              </button>
            )}
          </div>

          {/* Pestañas */}
          <div className="flex gap-1.5 mt-4">
            {(['doctores', 'consultorios'] as Tab[]).map(t => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className="px-5 py-2 rounded-xl text-sm font-medium transition-colors capitalize"
                style={tab === t
                  ? { background: '#C9A227', color: '#fff' }
                  : { background: 'rgba(255,255,255,0.6)', color: '#7A756C' }}
              >
                {t}
              </button>
            ))}
          </div>
        </div>

        {/* Estados de carga / error */}
        {cargando && (
          <div className="flex items-center justify-center gap-2 mt-16 text-amber-700">
            <Loader2 className="w-5 h-5 animate-spin" /> Cargando…
          </div>
        )}
        {conError && !cargando && (
          <div className="glass-card rounded-2xl mt-5 py-10 text-center text-sm text-red-600">
            No se pudo cargar la información de personal.
          </div>
        )}

        {/* ════ Doctores ════ */}
        {tab === 'doctores' && !cargando && !conError && (
          <div className="grid gap-4 mt-5" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(290px, 1fr))' }}>
            {doctores.map(d => (
              <button key={d.id} onClick={() => setDoctorSel(d)}
                className="glass-card rounded-2xl p-5 text-left transition-all duration-200 hover:-translate-y-1 hover:shadow-xl">
                <div className="flex items-start justify-between mb-3">
                  <div className="w-14 h-14 rounded-full flex items-center justify-center text-base font-bold shrink-0"
                    style={{ background: 'rgba(201,162,39,0.16)', color: '#B8860B' }}>
                    {initialesDoctor(d.nombre)}
                  </div>
                  <span className={`badge ${d.activo ? 'badge-success' : 'badge-neutral'}`}>
                    {d.activo ? 'Activo' : 'Inactivo'}
                  </span>
                </div>
                <h3 className="text-base font-semibold text-gray-900 leading-tight">{d.nombre}</h3>
                <p className="text-sm mb-3" style={{ color: '#B8860B' }}>{d.especialidad || '—'}</p>
                <div className="space-y-1.5 pt-3 border-t border-white/50">
                  <div className="flex items-center gap-2 text-xs text-gray-600">
                    <Fingerprint className="w-3.5 h-3.5 text-gray-400 shrink-0" /> Cédula {d.cedula || '—'}
                  </div>
                  <div className="flex items-center gap-2 text-xs text-gray-600">
                    <Clock className="w-3.5 h-3.5 text-gray-400 shrink-0" /> Cita de {d.duracion} min
                  </div>
                </div>
              </button>
            ))}
            {doctores.length === 0 && (
              <div className="col-span-full glass-card rounded-2xl py-16 text-center text-sm text-gray-500">
                Aún no hay doctores registrados.
              </div>
            )}
          </div>
        )}

        {/* ════ Consultorios ════ */}
        {tab === 'consultorios' && !cargando && !conError && (
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

                  {/* Acciones (solo si puede editar y está activo) */}
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
      </div>

      <DoctorDetalleDrawer doctor={doctorSel} onClose={() => setDoctorSel(null)} soloLectura />
      <NuevoDoctorDrawer open={nuevoDoctor} onClose={() => setNuevoDoc(false)} />
      <NuevoConsultorioDrawer open={nuevoConsul} onClose={() => setNuevoCons(false)} />
      <NuevoConsultorioDrawer open={editConsul !== null} editing={editConsul} onClose={() => setEditConsul(null)} />
    </div>
  )
}
