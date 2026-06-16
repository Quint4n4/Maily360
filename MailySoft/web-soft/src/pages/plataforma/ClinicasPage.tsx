import { useState, useEffect } from 'react'
import { Search, Building2, Loader2, AlertCircle, Plus } from 'lucide-react'
import PlatformLayout from '../../platform/PlatformLayout'
import { usePlatformRole } from '../../platform/PlatformRoleContext'
import { puedeEditarPlat } from '../../platform/permisos'
import { ESTADO_CLINICA } from '../../data/clinicas'
import { usePlatformClinicas, useSetClinicaEstado } from '../../hooks/plataforma'
import { formatMesAnio } from '../../lib/fecha'
import NuevaClinicaModal from '../../components/plataforma/NuevaClinicaModal'
import ClinicaDetailDrawer from '../../components/plataforma/ClinicaDetailDrawer'
import type { ClinicaPlat, EstadoClinica } from '../../types/plataforma'

type Filtro = 'todas' | EstadoClinica

const FILTROS: { key: Filtro; label: string }[] = [
  { key: 'todas',     label: 'Todas' },
  { key: 'active',    label: 'Activas' },
  { key: 'trial',     label: 'En prueba' },
  { key: 'suspended', label: 'Suspendidas' },
]

export default function ClinicasPage() {
  const { role } = usePlatformRole()
  const editar = puedeEditarPlat(role, 'clinicas')
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')
  const [filtro, setFiltro] = useState<Filtro>('todas')
  const [nuevaOpen, setNuevaOpen] = useState(false)
  const [detalleId, setDetalleId] = useState<string | null>(null)
  const cambiarEstado = useSetClinicaEstado()

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 350)
    return () => clearTimeout(t)
  }, [query])

  const { data, isLoading, isError } = usePlatformClinicas({
    search: debounced,
    status: filtro === 'todas' ? undefined : filtro,
  })
  const lista = data?.results ?? []
  const total = data?.count ?? 0

  const toggleEstado = (c: ClinicaPlat) => {
    const suspender = c.status !== 'suspended'
    if (suspender && !window.confirm(`¿Suspender a "${c.name}"? La clínica quedará bloqueada hasta reactivarla.`)) return
    cambiarEstado.mutate({ id: c.id, status: suspender ? 'suspended' : 'active' })
  }

  return (
    <PlatformLayout active="clinicas">
      {/* Cabecera */}
      <div className="glass-card rounded-2xl px-6 py-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Clínicas</h1>
            <p className="text-sm text-gray-500">
              {isLoading ? 'Cargando…' : `${total} clínica${total === 1 ? '' : 's'} en la plataforma`}
            </p>
          </div>
          {editar && (
            <button onClick={() => setNuevaOpen(true)}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110"
              style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}>
              <Plus className="w-4 h-4" /> Nueva clínica
            </button>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-3 mt-4">
          <div className="relative flex-1 min-w-[240px]">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
            <input value={query} onChange={e => setQuery(e.target.value)}
              placeholder="Buscar por nombre o slug" className="input pl-10" style={{ background: 'rgba(255,255,255,0.7)' }} />
          </div>
          <div className="flex gap-1.5">
            {FILTROS.map(f => (
              <button key={f.key} onClick={() => setFiltro(f.key)}
                className="px-4 py-2 rounded-xl text-sm font-medium transition-colors"
                style={filtro === f.key ? { background: '#C9A227', color: '#fff' } : { background: 'rgba(255,255,255,0.6)', color: '#7A756C' }}>
                {f.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {isError && (
        <div className="glass-card rounded-2xl py-10 px-6 flex items-center justify-center gap-3">
          <AlertCircle className="w-5 h-5 text-red-500 shrink-0" />
          <p className="text-sm text-red-600">No se pudieron cargar las clínicas.</p>
        </div>
      )}

      {isLoading && !isError && (
        <div className="flex items-center justify-center gap-2 py-16 text-amber-700">
          <Loader2 className="w-5 h-5 animate-spin" /> Cargando clínicas…
        </div>
      )}

      {/* Cards de clínicas */}
      {!isLoading && !isError && (
        <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))' }}>
          {lista.map(c => {
            const e = ESTADO_CLINICA[c.status]
            return (
              <div key={c.id} className="glass-card rounded-2xl p-5">
                <div className="flex items-start justify-between mb-3">
                  <div className="w-12 h-12 rounded-2xl flex items-center justify-center shrink-0" style={{ background: 'rgba(201,162,39,0.16)' }}>
                    <Building2 className="w-5 h-5" style={{ color: '#C9A227' }} />
                  </div>
                  <span className={`badge ${e.badge}`}>{e.label}</span>
                </div>
                <h3 className="text-base font-semibold text-gray-900">{c.name}</h3>
                <p className="text-xs text-gray-400 mb-3">Desde {formatMesAnio(c.created_at)}</p>

                <div className="grid grid-cols-2 gap-2 py-3 border-t border-white/50 text-center">
                  <div>
                    <p className="text-sm font-bold text-gray-800">{c.member_count ?? 0}</p>
                    <p className="text-[10px] text-gray-400">Usuarios</p>
                  </div>
                  <div>
                    <p className="text-sm font-bold text-gray-800">{(c.patient_count ?? 0).toLocaleString('es-MX')}</p>
                    <p className="text-[10px] text-gray-400">Pacientes</p>
                  </div>
                </div>

                <div className="flex gap-2 mt-3">
                  <button onClick={() => setDetalleId(c.id)} className="btn-secondary flex-1 text-xs py-2">
                    Ver detalle
                  </button>
                  {editar && (c.status === 'suspended' ? (
                    <button onClick={() => toggleEstado(c)} disabled={cambiarEstado.isPending}
                      className="flex-1 text-xs py-2 rounded-xl font-semibold text-white disabled:opacity-60" style={{ background: '#2E9E5B' }}>
                      Reactivar
                    </button>
                  ) : (
                    <button onClick={() => toggleEstado(c)} disabled={cambiarEstado.isPending}
                      className="flex-1 text-xs py-2 rounded-xl font-semibold disabled:opacity-60" style={{ background: '#FDE8E8', color: '#C0392B' }}>
                      Suspender
                    </button>
                  ))}
                </div>
              </div>
            )
          })}
          {lista.length === 0 && (
            <div className="col-span-full glass-card rounded-2xl py-16 text-center">
              <p className="text-gray-500 text-sm">No hay clínicas con ese criterio.</p>
            </div>
          )}
        </div>
      )}

      <NuevaClinicaModal open={nuevaOpen} onClose={() => setNuevaOpen(false)} />
      <ClinicaDetailDrawer clinicaId={detalleId} puedeEditar={editar} onClose={() => setDetalleId(null)} />
    </PlatformLayout>
  )
}
