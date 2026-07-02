import { useState, useEffect, Fragment } from 'react'
import {
  Search, Check, Loader2, AlertCircle, AlertTriangle, Building2, Layers,
  TrendingUp, ChevronLeft, ChevronRight, CreditCard,
} from 'lucide-react'
import PlatformLayout from '../../platform/PlatformLayout'
import { usePlatformRole } from '../../platform/PlatformRoleContext'
import { puedeEditarPlat } from '../../platform/permisos'
import { ESTADO_CLINICA, mxn } from '../../data/clinicas'
import { usePlatformPlanes, usePlatformSuscripciones, useSuscripcionesResumen } from '../../hooks/plataforma'
import AsignarPlanModal from '../../components/plataforma/AsignarPlanModal'
import { formatFechaCorta, fromDayKey } from '../../lib/fecha'
import { ALERTA_SUSCRIPCION } from '../../types/plataforma'
import type { SuscripcionRow } from '../../types/plataforma'

type FiltroAlerta = 'todas' | 'vencidas' | 'por_vencer'

const CHIPS: { key: FiltroAlerta; label: string }[] = [
  { key: 'todas',      label: 'Todas' },
  { key: 'vencidas',   label: 'Vencidas' },
  { key: 'por_vencer', label: 'Por vencer' },
]

const GRID = '1.8fr 1fr 0.8fr 1fr 1fr 1.2fr 0.9fr 1.1fr'

/** "Vence el": trial_ends_at (ISO) si está en prueba; si no, current_period_end (YYYY-MM-DD). */
function fechaVence(r: SuscripcionRow): string {
  const v = r.tenant_status === 'trial' ? r.trial_ends_at : r.current_period_end
  if (!v) return '—'
  // Las fechas 'YYYY-MM-DD' se parsean en local (no UTC) para no correrse un día.
  const d = /^\d{4}-\d{2}-\d{2}$/.test(v) ? fromDayKey(v) : new Date(v)
  return formatFechaCorta(d.toISOString())
}

const CICLO: Record<string, string> = { monthly: 'Mensual', annual: 'Anual' }

/** Badge de alerta de vencimiento (o nada). */
function AlertaBadge({ row }: { row: SuscripcionRow }) {
  if (!row.alerta) return <span className="text-sm text-gray-300">—</span>
  const a = ALERTA_SUSCRIPCION[row.alerta]
  return <span className={`badge ${a.badge}`}>{a.label}</span>
}

export default function SuscripcionesPage() {
  const { role } = usePlatformRole()
  const editar = puedeEditarPlat(role, 'suscripciones')

  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')
  const [planFiltro, setPlanFiltro] = useState('')
  const [chip, setChip] = useState<FiltroAlerta>('todas')
  const [page, setPage] = useState(1)
  const [seleccion, setSeleccion] = useState<SuscripcionRow | null>(null)

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 350)
    return () => clearTimeout(t)
  }, [query])

  // Al cambiar cualquier filtro se vuelve a la primera página.
  useEffect(() => { setPage(1) }, [debounced, planFiltro, chip])

  const planes = usePlatformPlanes()
  const resumen = useSuscripcionesResumen()
  const { data, isLoading, isError, isFetching } = usePlatformSuscripciones({
    search: debounced || undefined,
    plan_id: planFiltro || undefined,
    alerta: chip === 'todas' ? undefined : chip,
    page,
  })

  const lista = data?.results ?? []
  const total = data?.count ?? 0

  const planesActivos = (planes.data ?? []).filter(p => p.is_active).sort((a, b) => a.order - b.order)
  const alertas = resumen.data?.alertas
  const vencidas = (alertas?.trial_vencido ?? 0) + (alertas?.periodo_vencido ?? 0)
  const cuentaPlan = (planId: string): number =>
    resumen.data?.por_plan.find(p => p.plan_id === planId)?.count ?? 0

  const kpis = [
    { icon: Building2,  label: 'Clínicas totales', valor: (resumen.data?.total_clinicas ?? 0).toLocaleString('es-MX'), color: '#3A6EA5' },
    { icon: Layers,     label: 'Sin plan',         valor: (resumen.data?.sin_plan ?? 0).toLocaleString('es-MX'),       color: '#C9A227' },
    { icon: TrendingUp, label: 'MRR estimado',     valor: mxn(Number(resumen.data?.mrr_estimado ?? 0)),                color: '#2E7D5B' },
  ]

  const cargando = (isLoading || planes.isLoading || resumen.isLoading) && !isError
  const conError = isError || planes.isError || resumen.isError

  return (
    <PlatformLayout active="suscripciones">
      {/* Cabecera + filtros */}
      <div className="glass-card rounded-2xl px-6 py-5">
        <h1 className="text-2xl font-bold text-gray-900">Suscripciones</h1>
        <p className="text-sm text-gray-500">
          {isLoading ? 'Cargando…' : `${total.toLocaleString('es-MX')} clínica${total === 1 ? '' : 's'} · planes y vencimientos`}
        </p>

        <div className="flex flex-wrap items-center gap-3 mt-4">
          <div className="relative flex-1 min-w-[220px]">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
            <input value={query} onChange={e => setQuery(e.target.value)}
              placeholder="Buscar por nombre o slug" className="input pl-10" style={{ background: 'rgba(255,255,255,0.7)' }} />
          </div>

          <select value={planFiltro} onChange={e => setPlanFiltro(e.target.value)}
            className="input w-auto min-w-[160px]" style={{ background: 'rgba(255,255,255,0.7)' }} aria-label="Filtrar por plan">
            <option value="">Todos los planes</option>
            {planesActivos.map(p => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>

          <div className="flex gap-1.5">
            {CHIPS.map(f => (
              <button key={f.key} onClick={() => setChip(f.key)}
                className="px-4 py-2 rounded-xl text-sm font-medium transition-colors"
                style={chip === f.key ? { background: '#C9A227', color: '#fff' } : { background: 'rgba(255,255,255,0.6)', color: '#7A756C' }}>
                {f.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Banner de alertas: solo si hay vencidas (la suspensión SIEMPRE es manual) */}
      {vencidas > 0 && (
        <div className="glass-card rounded-2xl px-5 py-4 flex flex-wrap items-center justify-between gap-3"
          style={{ border: '1px solid rgba(192,57,43,0.35)', background: 'rgba(192,57,43,0.07)' }}>
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0" style={{ background: 'rgba(192,57,43,0.12)' }}>
              <AlertTriangle className="w-5 h-5" style={{ color: '#C0392B' }} />
            </div>
            <p className="text-sm" style={{ color: '#8C2B21' }}>
              <strong>{vencidas} clínica{vencidas === 1 ? '' : 's'}</strong> con la prueba o el periodo vencido — la suspensión es manual.
            </p>
          </div>
          <button onClick={() => setChip('vencidas')}
            className="px-4 py-2 rounded-xl text-xs font-semibold text-white transition-all hover:brightness-110"
            style={{ background: '#C0392B' }}>
            Ver vencidas
          </button>
        </div>
      )}

      {conError && (
        <div className="glass-card rounded-2xl py-10 px-6 flex items-center justify-center gap-3">
          <AlertCircle className="w-5 h-5 text-red-500 shrink-0" />
          <p className="text-sm text-red-600">No se pudieron cargar las suscripciones. ¿Tienes permiso para verlas?</p>
        </div>
      )}

      {cargando && !conError && (
        <div className="flex items-center justify-center gap-2 py-16 text-amber-700">
          <Loader2 className="w-5 h-5 animate-spin" /> Cargando suscripciones…
        </div>
      )}

      {!cargando && !conError && (
        <>
          {/* KPIs del resumen */}
          <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
            {kpis.map(({ icon: Icon, label, valor, color }) => (
              <div key={label} className="glass-card rounded-2xl p-5">
                <div className="w-10 h-10 rounded-xl flex items-center justify-center mb-3" style={{ background: `${color}1A` }}>
                  <Icon className="w-5 h-5" style={{ color }} />
                </div>
                <p className="text-2xl font-bold text-gray-900">{valor}</p>
                <p className="text-sm text-gray-500 mt-0.5">{label}</p>
              </div>
            ))}
          </div>

          {/* Planes reales */}
          <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))' }}>
            {planesActivos.map(p => (
              <div key={p.id} className="glass-card rounded-2xl p-6 relative"
                style={p.is_featured ? { border: '2px solid #C9A227' } : {}}>
                {p.is_featured && (
                  <span className="absolute top-4 right-4 text-[10px] font-semibold uppercase px-2 py-0.5 rounded-full"
                    style={{ background: '#C9A227', color: '#fff' }}>Popular</span>
                )}
                <h3 className="text-lg font-bold text-gray-900">{p.name}</h3>
                {p.description && <p className="text-xs text-gray-500 mt-0.5">{p.description}</p>}
                <p className="mt-1">
                  <span className="text-2xl font-bold" style={{ color: '#B8860B' }}>{mxn(Number(p.price_monthly))}</span>
                  <span className="text-sm text-gray-400">/mes</span>
                </p>
                <p className="text-xs text-gray-400 mt-1 mb-4">
                  {cuentaPlan(p.id)} clínica{cuentaPlan(p.id) === 1 ? '' : 's'} en este plan
                </p>
                <ul className="space-y-2">
                  {p.features.map(f => (
                    <li key={f} className="flex items-center gap-2 text-sm text-gray-600">
                      <Check className="w-4 h-4 shrink-0" style={{ color: '#2E7D5B' }} /> {f}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
            {planesActivos.length === 0 && (
              <div className="col-span-full glass-card rounded-2xl py-10 text-center">
                <p className="text-sm text-gray-400">Aún no hay planes configurados.</p>
              </div>
            )}
          </div>

          {/* Tabla / tarjetas de clínicas */}
          <div className="glass-card rounded-2xl overflow-hidden">
            <div className="px-4 sm:px-6 py-4 border-b border-white/50">
              <h2 className="text-base font-semibold text-gray-800">Clínicas suscritas</h2>
            </div>

            {/* Encabezado de tabla (solo escritorio) */}
            <div className="hidden md:grid items-center px-6 py-3 text-xs font-semibold text-gray-500 border-b border-white/40"
              style={{ gridTemplateColumns: GRID }}>
              <span>Clínica</span><span>Plan</span><span>Ciclo</span><span>Vence el</span>
              <span>Estado</span><span>Alerta</span><span>Ingreso/mes</span><span />
            </div>

            {lista.map(r => {
              const e = ESTADO_CLINICA[r.tenant_status]
              const ingreso = r.plan_price_monthly ? mxn(Number(r.plan_price_monthly)) : '—'
              return (
                <Fragment key={r.tenant_id}>
                  {/* Móvil: tarjeta apilada */}
                  <div className="md:hidden px-4 py-3.5 border-b border-white/30">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-sm font-semibold text-gray-800 truncate">{r.tenant_name}</p>
                        <p className="text-xs text-gray-500 mt-0.5">
                          {r.plan_name ?? 'Sin plan'}
                          {r.billing_cycle ? ` · ${CICLO[r.billing_cycle]}` : ''}
                        </p>
                      </div>
                      <span className="text-sm font-bold text-gray-900 shrink-0">{ingreso}</span>
                    </div>
                    <p className="text-xs text-gray-500 mt-1.5">Vence el {fechaVence(r)}</p>
                    <div className="flex flex-wrap items-center gap-1.5 mt-2.5">
                      <span className={`badge ${e.badge}`}>{e.label}</span>
                      {r.alerta && (
                        <span className={`badge ${ALERTA_SUSCRIPCION[r.alerta].badge}`}>{ALERTA_SUSCRIPCION[r.alerta].label}</span>
                      )}
                    </div>
                    {editar && (
                      <button onClick={() => setSeleccion(r)}
                        className="btn-secondary w-full mt-3 text-xs py-2 inline-flex items-center justify-center gap-1.5">
                        <CreditCard className="w-3.5 h-3.5" /> {r.plan_id ? 'Cambiar plan' : 'Asignar plan'}
                      </button>
                    )}
                  </div>

                  {/* Escritorio: fila de tabla */}
                  <div className="hidden md:grid items-center px-6 py-3 border-b border-white/30"
                    style={{ gridTemplateColumns: GRID }}>
                    <span className="min-w-0 pr-2">
                      <span className="block text-sm font-medium text-gray-800 truncate">{r.tenant_name}</span>
                      <span className="block text-xs text-gray-400 truncate">{r.tenant_slug}</span>
                    </span>
                    <span className="text-sm text-gray-600 truncate pr-2">{r.plan_name ?? 'Sin plan'}</span>
                    <span className="text-sm text-gray-600 pr-2">{r.billing_cycle ? CICLO[r.billing_cycle] : '—'}</span>
                    <span className="text-sm text-gray-600 pr-2">{fechaVence(r)}</span>
                    <span className="pr-2"><span className={`badge ${e.badge}`}>{e.label}</span></span>
                    <span className="pr-2"><AlertaBadge row={r} /></span>
                    <span className="text-sm font-semibold text-gray-800 pr-2">{ingreso}</span>
                    <span>
                      {editar && (
                        <button onClick={() => setSeleccion(r)} className="btn-secondary text-xs py-2 px-3 whitespace-nowrap">
                          {r.plan_id ? 'Cambiar plan' : 'Asignar plan'}
                        </button>
                      )}
                    </span>
                  </div>
                </Fragment>
              )
            })}

            {lista.length === 0 && (
              <div className="px-4 sm:px-6 py-14 text-center">
                <CreditCard className="w-8 h-8 mx-auto mb-2 text-gray-300" />
                <p className="text-sm text-gray-400">No hay clínicas con esos filtros.</p>
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
        </>
      )}

      {seleccion && (
        <AsignarPlanModal row={seleccion} planes={planes.data ?? []} onClose={() => setSeleccion(null)} />
      )}
    </PlatformLayout>
  )
}
