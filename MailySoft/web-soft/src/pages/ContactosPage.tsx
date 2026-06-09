import { useState, useEffect } from 'react'
import { Search, Plus, Phone, CalendarDays, Loader2, AlertCircle, AlertTriangle } from 'lucide-react'
import Topbar from '../components/Topbar'
import NuevoPacienteDrawer from '../components/contactos/NuevoPacienteDrawer'
import EditarPacienteDrawer from '../components/contactos/EditarPacienteDrawer'
import ExpedienteDrawer from '../components/contactos/ExpedienteDrawer'
import { usePatients, useDeactivatePatient } from '../hooks/pacientes'
import { initialsOf } from '../lib/paciente'
import type { PatientOut } from '../types/paciente'
import { useRole } from '../auth/RoleContext'
import { puedeEditar, puedeVerExpedienteClinico } from '../auth/permisos'

export default function ContactosPage() {
  const [query, setQuery]         = useState('')
  const [debounced, setDebounced] = useState('')
  const [nuevoOpen, setNuevo]     = useState(false)
  const [verPaciente, setVer]     = useState<PatientOut | null>(null)
  const [editarPaciente, setEditar] = useState<PatientOut | null>(null)
  const { role } = useRole()
  const editar = puedeEditar(role, 'contactos')
  const verClinico = puedeVerExpedienteClinico(role)
  const baja = useDeactivatePatient()

  const abrirEdicion = () => {
    if (!verPaciente) return
    setEditar(verPaciente)
    setVer(null)
  }

  const darDeBaja = () => {
    if (!verPaciente) return
    const ok = window.confirm(
      `¿Dar de baja a ${verPaciente.full_name}? Dejará de aparecer en la lista (no se borra de la base de datos).`,
    )
    if (!ok) return
    baja.mutate(verPaciente.id, { onSuccess: () => setVer(null) })
  }

  // Debounce de la búsqueda: 350 ms tras dejar de teclear → menos llamadas al backend.
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 350)
    return () => clearTimeout(t)
  }, [query])

  const { data, isLoading, isError, error } = usePatients(debounced)
  const lista = data?.results ?? []
  const total = data?.count ?? 0

  return (
    <div className="min-h-screen relative">

      {/* Fondo */}
      <div className="fixed inset-0 -z-10" style={{ background: 'linear-gradient(135deg, #b89a52 0%, #d8c690 45%, #f1e8cf 100%)' }} />
      <div className="fixed inset-0 -z-10 bg-cover bg-center" style={{ backgroundImage: "url('/fondo-agenda.jpg')" }} />
      <div className="fixed inset-0 -z-10" style={{ background: 'rgba(255,255,255,0.20)' }} />

      <Topbar active="contactos" />

      <div className="p-5 max-w-[1300px] mx-auto">

        {/* ════ Cabecera: título + buscador ════ */}
        <div className="glass-card rounded-2xl px-6 py-5">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">Contactos</h1>
              <p className="text-sm text-gray-500">
                {isLoading ? 'Cargando…' : `${total} paciente${total === 1 ? '' : 's'} registrado${total === 1 ? '' : 's'}`}
              </p>
            </div>
            {editar && (
              <button
                onClick={() => setNuevo(true)}
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110"
                style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
              >
                <Plus className="w-4 h-4" /> Nuevo paciente
              </button>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-3 mt-4">
            <div className="relative flex-1 min-w-[240px]">
              <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
              <input
                value={query} onChange={e => setQuery(e.target.value)}
                placeholder="Buscar por nombre, apellido, teléfono o expediente"
                className="input pl-10"
                style={{ background: 'rgba(255,255,255,0.7)' }}
              />
            </div>
          </div>
        </div>

        {/* ════ Estado de error ════ */}
        {isError && (
          <div className="glass-card rounded-2xl mt-7 py-10 px-6 flex items-center justify-center gap-3 text-center">
            <AlertCircle className="w-5 h-5 text-red-500 shrink-0" />
            <p className="text-sm text-red-600">
              No se pudieron cargar los pacientes. {error instanceof Error ? error.message : ''}
            </p>
          </div>
        )}

        {/* ════ Estado de carga ════ */}
        {isLoading && !isError && (
          <div className="flex items-center justify-center gap-2 mt-16 text-amber-700">
            <Loader2 className="w-5 h-5 animate-spin" /> Cargando pacientes…
          </div>
        )}

        {/* ════ Cuadrícula de carpetas (folders) ════ */}
        {!isLoading && !isError && (
          <div className="grid gap-5 mt-7" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}>
            {lista.map(p => (
              <div key={p.id} className="group relative pt-6 transition-transform duration-200 hover:-translate-y-1.5">

                {/* Pestaña de la carpeta (lengüeta con el número de expediente) */}
                <div
                  className="absolute top-0 left-6 z-0 px-4 pt-1.5 pb-3 rounded-t-xl text-[11px] font-bold tracking-wide"
                  style={{
                    background: 'rgba(255,255,255,0.58)',
                    backdropFilter: 'blur(18px)',
                    borderTop: '1px solid rgba(255,255,255,0.7)',
                    borderLeft: '1px solid rgba(255,255,255,0.7)',
                    borderRight: '1px solid rgba(255,255,255,0.7)',
                    color: '#B8860B',
                  }}
                >
                  {p.record_number}
                </div>

                {/* Cuerpo de la carpeta */}
                <button
                  onClick={() => setVer(p)}
                  className="relative z-10 glass-card rounded-2xl p-5 w-full text-left transition-shadow duration-200 group-hover:shadow-xl"
                >
                  <div className="flex items-start justify-between mb-3">
                    <div className="w-12 h-12 rounded-full flex items-center justify-center text-sm font-bold shrink-0"
                      style={{ background: 'rgba(201,162,39,0.16)', color: '#B8860B' }}>
                      {initialsOf(p)}
                    </div>
                    {p.is_provisional ? (
                      <span className="badge" style={{ background: '#FBF1D9', color: '#9A7B1E' }}>Por completar</span>
                    ) : (
                      <span className={`badge ${p.is_active ? 'badge-success' : 'badge-neutral'}`}>
                        {p.is_active ? 'Activo' : 'Inactivo'}
                      </span>
                    )}
                  </div>

                  <h3 className="text-base font-semibold text-gray-900 leading-tight truncate">{p.full_name}</h3>
                  {p.is_provisional ? (
                    <div className="flex items-center gap-1 text-[11px] mb-3" style={{ color: '#9A7B1E' }}>
                      <AlertTriangle className="w-3 h-3 shrink-0" /> Falta completar datos personales
                    </div>
                  ) : (
                    <p className="text-xs text-gray-400 mb-3">{p.sex_display || '—'}</p>
                  )}

                  <div className="space-y-1.5 pt-3 border-t border-white/50">
                    <div className="flex items-center gap-2 text-xs text-gray-600">
                      <Phone className="w-3.5 h-3.5 text-gray-400 shrink-0" /> {p.phone || '—'}
                    </div>
                    <div className="flex items-center gap-2 text-xs text-gray-600">
                      <CalendarDays className="w-3.5 h-3.5 text-gray-400 shrink-0" /> Última: —
                    </div>
                  </div>
                </button>
              </div>
            ))}

            {/* Estado vacío */}
            {lista.length === 0 && (
              <div className="col-span-full glass-card rounded-2xl py-16 text-center">
                <p className="text-gray-500 text-sm">
                  {debounced
                    ? 'No encontramos pacientes con ese criterio.'
                    : 'Aún no hay pacientes registrados. Crea el primero con “Nuevo paciente”.'}
                </p>
              </div>
            )}
          </div>
        )}
      </div>

      <NuevoPacienteDrawer open={nuevoOpen} onClose={() => setNuevo(false)} />
      <EditarPacienteDrawer paciente={editarPaciente} onClose={() => setEditar(null)} />
      <ExpedienteDrawer
        paciente={verPaciente}
        onClose={() => setVer(null)}
        verClinico={verClinico}
        puedeEditar={editar}
        onEditar={abrirEdicion}
        onDarDeBaja={darDeBaja}
        dandoDeBaja={baja.isPending}
      />
    </div>
  )
}
