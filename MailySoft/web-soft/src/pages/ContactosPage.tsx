import { useState, useMemo } from 'react'
import { Search, Plus, Phone, CalendarDays } from 'lucide-react'
import Topbar from '../components/Topbar'
import NuevoPacienteDrawer from '../components/contactos/NuevoPacienteDrawer'
import ExpedienteDrawer from '../components/contactos/ExpedienteDrawer'
import { PACIENTES, Paciente, fullName, initials, SEXO_LABEL } from '../data/pacientes'

type Filtro = 'todos' | 'activos' | 'inactivos'

const FILTROS: { key: Filtro; label: string }[] = [
  { key: 'todos',     label: 'Todos' },
  { key: 'activos',   label: 'Activos' },
  { key: 'inactivos', label: 'Inactivos' },
]

export default function ContactosPage() {
  const [query, setQuery]     = useState('')
  const [filtro, setFiltro]   = useState<Filtro>('todos')
  const [nuevoOpen, setNuevo] = useState(false)
  const [verPaciente, setVer] = useState<Paciente | null>(null)

  const lista = useMemo(() => {
    const q = query.trim().toLowerCase()
    return PACIENTES.filter(p => {
      if (filtro === 'activos'   && !p.activo) return false
      if (filtro === 'inactivos' &&  p.activo) return false
      if (!q) return true
      return (
        fullName(p).toLowerCase().includes(q) ||
        p.curp.toLowerCase().includes(q) ||
        p.expediente.toLowerCase().includes(q)
      )
    })
  }, [query, filtro])

  return (
    <div className="min-h-screen relative">

      {/* Fondo */}
      <div className="fixed inset-0 -z-10" style={{ background: 'linear-gradient(135deg, #b89a52 0%, #d8c690 45%, #f1e8cf 100%)' }} />
      <div className="fixed inset-0 -z-10 bg-cover bg-center" style={{ backgroundImage: "url('/fondo-agenda.jpg')" }} />
      <div className="fixed inset-0 -z-10" style={{ background: 'rgba(255,255,255,0.20)' }} />

      <Topbar active="contactos" />

      <div className="p-5 max-w-[1300px] mx-auto">

        {/* ════ Cabecera: título + buscador + filtros ════ */}
        <div className="glass-card rounded-2xl px-6 py-5">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">Contactos</h1>
              <p className="text-sm text-gray-500">{PACIENTES.length} pacientes registrados</p>
            </div>
            <button
              onClick={() => setNuevo(true)}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110"
              style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
            >
              <Plus className="w-4 h-4" /> Nuevo paciente
            </button>
          </div>

          <div className="flex flex-wrap items-center gap-3 mt-4">
            <div className="relative flex-1 min-w-[240px]">
              <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
              <input
                value={query} onChange={e => setQuery(e.target.value)}
                placeholder="Buscar por nombre, CURP o número de expediente"
                className="input pl-10"
                style={{ background: 'rgba(255,255,255,0.7)' }}
              />
            </div>
            <div className="flex gap-1.5">
              {FILTROS.map(f => (
                <button
                  key={f.key}
                  onClick={() => setFiltro(f.key)}
                  className="px-4 py-2 rounded-xl text-sm font-medium transition-colors"
                  style={filtro === f.key
                    ? { background: '#C9A227', color: '#fff' }
                    : { background: 'rgba(255,255,255,0.6)', color: '#7A756C' }}
                >
                  {f.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* ════ Cuadrícula de carpetas (folders) ════ */}
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
                {p.expediente}
              </div>

              {/* Cuerpo de la carpeta */}
              <button
                onClick={() => setVer(p)}
                className="relative z-10 glass-card rounded-2xl p-5 w-full text-left transition-shadow duration-200 group-hover:shadow-xl"
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="w-12 h-12 rounded-full flex items-center justify-center text-sm font-bold shrink-0"
                    style={{ background: 'rgba(201,162,39,0.16)', color: '#B8860B' }}>
                    {initials(p)}
                  </div>
                  <span className={`badge ${p.activo ? 'badge-success' : 'badge-neutral'}`}>
                    {p.activo ? 'Activo' : 'Inactivo'}
                  </span>
                </div>

                <h3 className="text-base font-semibold text-gray-900 leading-tight truncate">{fullName(p)}</h3>
                <p className="text-xs text-gray-400 mb-3">{SEXO_LABEL[p.sexo]}</p>

                <div className="space-y-1.5 pt-3 border-t border-white/50">
                  <div className="flex items-center gap-2 text-xs text-gray-600">
                    <Phone className="w-3.5 h-3.5 text-gray-400 shrink-0" /> {p.telefono}
                  </div>
                  <div className="flex items-center gap-2 text-xs text-gray-600">
                    <CalendarDays className="w-3.5 h-3.5 text-gray-400 shrink-0" /> Última: {p.ultimaCita ?? '—'}
                  </div>
                </div>
              </button>
            </div>
          ))}

          {/* Estado vacío */}
          {lista.length === 0 && (
            <div className="col-span-full glass-card rounded-2xl py-16 text-center">
              <p className="text-gray-500 text-sm">No encontramos pacientes con ese criterio.</p>
            </div>
          )}
        </div>
      </div>

      <NuevoPacienteDrawer open={nuevoOpen} onClose={() => setNuevo(false)} />
      <ExpedienteDrawer paciente={verPaciente} onClose={() => setVer(null)} />
    </div>
  )
}
