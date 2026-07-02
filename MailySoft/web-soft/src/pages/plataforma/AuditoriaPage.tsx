import { useState, useEffect, Fragment } from 'react'
import { Search, ScrollText, Loader2, AlertCircle, Building2, User, ChevronLeft, ChevronRight } from 'lucide-react'
import PlatformLayout from '../../platform/PlatformLayout'
import { usePlatformAuditoria, usePlatformClinicas } from '../../hooks/plataforma'
import { formatFechaHora } from '../../lib/fecha'
import { ACCIONES_AUDITORIA } from '../../types/plataforma'
import type { AuditoriaEvento } from '../../types/plataforma'

/** Badge dorado para la acción del evento. */
function AccionBadge({ evento }: { evento: AuditoriaEvento }) {
  return (
    <span className="inline-block text-[11px] font-semibold px-2.5 py-1 rounded-full whitespace-nowrap"
      style={{ background: 'rgba(201,162,39,0.16)', color: '#B8860B' }}>
      {evento.action_display || evento.action}
    </span>
  )
}

/** Línea secundaria: recurso afectado + IP (si existen). */
function DetalleSecundario({ evento }: { evento: AuditoriaEvento }) {
  const recurso = evento.resource_type
    ? `${evento.resource_type}${evento.resource_id ? ` · ${evento.resource_id}` : ''}`
    : null
  if (!recurso && !evento.ip_address) return null
  return (
    <p className="text-[11px] text-gray-400 mt-0.5 truncate">
      {recurso}
      {recurso && evento.ip_address ? ' — ' : ''}
      {evento.ip_address ? `IP ${evento.ip_address}` : ''}
    </p>
  )
}

const GRID = '1.1fr 1.2fr 1.4fr 1.1fr 2fr'

export default function AuditoriaPage() {
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')
  const [clinica, setClinica] = useState('')
  const [accion, setAccion] = useState('')
  const [desde, setDesde] = useState('')
  const [hasta, setHasta] = useState('')
  const [page, setPage] = useState(1)

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 350)
    return () => clearTimeout(t)
  }, [query])

  // Al cambiar cualquier filtro se vuelve a la primera página.
  useEffect(() => { setPage(1) }, [debounced, clinica, accion, desde, hasta])

  const { data, isLoading, isError, isFetching } = usePlatformAuditoria({
    search: debounced || undefined,
    tenant_id: clinica || undefined,
    action: accion || undefined,
    date_from: desde || undefined,
    date_to: hasta || undefined,
    page,
  })
  const clinicas = usePlatformClinicas({})
  const lista = data?.results ?? []
  const total = data?.count ?? 0

  return (
    <PlatformLayout active="auditoria">
      {/* Cabecera + filtros */}
      <div className="glass-card rounded-2xl px-6 py-5">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Auditoría</h1>
          <p className="text-sm text-gray-500">
            {isLoading ? 'Cargando…' : `${total.toLocaleString('es-MX')} evento${total === 1 ? '' : 's'} registrado${total === 1 ? '' : 's'}`}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3 mt-4">
          <div className="relative flex-1 min-w-[220px]">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
            <input value={query} onChange={e => setQuery(e.target.value)}
              placeholder="Buscar por actor o descripción" className="input pl-10" style={{ background: 'rgba(255,255,255,0.7)' }} />
          </div>

          <select value={clinica} onChange={e => setClinica(e.target.value)}
            className="input w-auto min-w-[160px]" style={{ background: 'rgba(255,255,255,0.7)' }} aria-label="Filtrar por clínica">
            <option value="">Todas las clínicas</option>
            {(clinicas.data?.results ?? []).map(c => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>

          <select value={accion} onChange={e => setAccion(e.target.value)}
            className="input w-auto min-w-[160px]" style={{ background: 'rgba(255,255,255,0.7)' }} aria-label="Filtrar por acción">
            <option value="">Todas las acciones</option>
            {ACCIONES_AUDITORIA.map(a => (
              <option key={a.value} value={a.value}>{a.label}</option>
            ))}
          </select>

          <div className="flex items-center gap-2">
            <label className="text-xs text-gray-500" htmlFor="aud-desde">Del</label>
            <input id="aud-desde" type="date" value={desde} onChange={e => setDesde(e.target.value)}
              className="input w-auto" style={{ background: 'rgba(255,255,255,0.7)' }} />
            <label className="text-xs text-gray-500" htmlFor="aud-hasta">al</label>
            <input id="aud-hasta" type="date" value={hasta} onChange={e => setHasta(e.target.value)}
              className="input w-auto" style={{ background: 'rgba(255,255,255,0.7)' }} />
          </div>
        </div>
      </div>

      {isError && (
        <div className="glass-card rounded-2xl py-10 px-6 flex items-center justify-center gap-3">
          <AlertCircle className="w-5 h-5 text-red-500 shrink-0" />
          <p className="text-sm text-red-600">No se pudo cargar la auditoría. ¿Tienes permiso para verla?</p>
        </div>
      )}

      {isLoading && !isError && (
        <div className="flex items-center justify-center gap-2 py-16 text-amber-700">
          <Loader2 className="w-5 h-5 animate-spin" /> Cargando auditoría…
        </div>
      )}

      {!isLoading && !isError && (
        <div className="glass-card rounded-2xl overflow-hidden">
          {/* Encabezado de tabla (solo escritorio) */}
          <div className="hidden md:grid items-center px-6 py-3 text-xs font-semibold text-gray-500 border-b border-white/40"
            style={{ gridTemplateColumns: GRID }}>
            <span>Fecha y hora</span><span>Acción</span><span>Actor</span><span>Clínica</span><span>Descripción</span>
          </div>

          {lista.map(ev => (
            <Fragment key={ev.id}>
              {/* Móvil: tarjeta apilada */}
              <div className="md:hidden px-4 py-3.5 border-b border-white/30">
                <div className="flex items-center justify-between gap-2">
                  <AccionBadge evento={ev} />
                  <span className="text-[11px] text-gray-400 shrink-0">{formatFechaHora(ev.created_at)}</span>
                </div>
                <p className="text-sm text-gray-700 mt-2">{ev.description}</p>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500 mt-1.5">
                  <span className="flex items-center gap-1 min-w-0">
                    <User className="w-3.5 h-3.5 text-gray-400 shrink-0" />
                    <span className="truncate">{ev.actor_email ?? 'Sistema'}{ev.actor_role ? ` · ${ev.actor_role}` : ''}</span>
                  </span>
                  {ev.tenant_name && (
                    <span className="flex items-center gap-1 min-w-0">
                      <Building2 className="w-3.5 h-3.5 text-gray-400 shrink-0" />
                      <span className="truncate">{ev.tenant_name}</span>
                    </span>
                  )}
                </div>
                <DetalleSecundario evento={ev} />
              </div>

              {/* Escritorio: fila de tabla */}
              <div className="hidden md:grid items-center px-6 py-3 border-b border-white/30"
                style={{ gridTemplateColumns: GRID }}>
                <span className="text-sm text-gray-600 pr-2">{formatFechaHora(ev.created_at)}</span>
                <span className="pr-2"><AccionBadge evento={ev} /></span>
                <span className="min-w-0 pr-2">
                  <span className="block text-sm text-gray-800 truncate">{ev.actor_email ?? 'Sistema'}</span>
                  {ev.actor_role && <span className="block text-xs text-gray-400 truncate">{ev.actor_role}</span>}
                </span>
                <span className="text-sm text-gray-600 truncate pr-2">{ev.tenant_name ?? '—'}</span>
                <span className="min-w-0">
                  <span className="block text-sm text-gray-700 truncate">{ev.description}</span>
                  <DetalleSecundario evento={ev} />
                </span>
              </div>
            </Fragment>
          ))}

          {lista.length === 0 && (
            <div className="px-4 sm:px-6 py-14 text-center">
              <ScrollText className="w-8 h-8 mx-auto mb-2 text-gray-300" />
              <p className="text-sm text-gray-400">No hay eventos con esos filtros.</p>
            </div>
          )}

          {/* Paginación (patrón next/previous de DRF) */}
          {(data?.previous || data?.next) && (
            <div className="flex items-center justify-between px-4 sm:px-6 py-3">
              <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={!data?.previous || isFetching}
                className="btn-secondary inline-flex items-center gap-1.5 text-xs py-2 px-3 disabled:opacity-40">
                <ChevronLeft className="w-4 h-4" /> Anterior
              </button>
              <span className="text-xs text-gray-500">
                Página {page}{isFetching ? ' · actualizando…' : ''}
              </span>
              <button onClick={() => setPage(p => p + 1)} disabled={!data?.next || isFetching}
                className="btn-secondary inline-flex items-center gap-1.5 text-xs py-2 px-3 disabled:opacity-40">
                Siguiente <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          )}
        </div>
      )}
    </PlatformLayout>
  )
}
