import { useNavigate } from 'react-router-dom'
import {
  Activity, AlertCircle, AlertTriangle, ArrowRight, CheckCircle2, Cpu, Database,
  FileText, Loader2, Package, RefreshCw, ScrollText, Server, XCircle,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import PlatformLayout from '../../platform/PlatformLayout'
import { usePlatformSistema } from '../../hooks/plataforma'
import type { SistemaEstado, SistemaServicio } from '../../types/plataforma'

/** Colores + etiqueta en español por estado (mismos verdes/rojos del portal). */
const ESTADO_META: Record<SistemaEstado, { label: string; color: string; Icon: LucideIcon }> = {
  operational: { label: 'Operativo',  color: '#2E7D5B', Icon: CheckCircle2 },
  degraded:    { label: 'Degradado',  color: '#B45309', Icon: AlertTriangle },
  down:        { label: 'Caído',      color: '#C0392B', Icon: XCircle },
}

const BANNER_TEXTO: Record<SistemaEstado, string> = {
  operational: 'Todos los sistemas operativos',
  degraded: 'Rendimiento degradado en algunos servicios',
  down: 'Hay servicios caídos',
}

/** Icono por servicio (según la key del backend). */
const SERVICIO_ICONO: Record<string, LucideIcon> = {
  database: Database,
  redis: Server,
  celery_worker: Cpu,
}

/** Tiempo relativo legible ("hace 15 s", "hace 2 min"). */
function hace(iso: string): string {
  const seg = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000))
  if (seg < 60) return `hace ${seg} s`
  const min = Math.floor(seg / 60)
  if (min < 60) return `hace ${min} min`
  const h = Math.floor(min / 60)
  if (h < 24) return `hace ${h} h`
  return `hace ${Math.floor(h / 24)} d`
}

/** Badge de estado en español (Operativo / Degradado / Caído). */
function EstadoBadge({ status }: { status: SistemaEstado }) {
  const meta = ESTADO_META[status]
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold px-2.5 py-1 rounded-full whitespace-nowrap"
      style={{ background: `${meta.color}1A`, color: meta.color }}>
      <meta.Icon className="w-3.5 h-3.5" />
      {meta.label}
    </span>
  )
}

/** Card de un servicio monitoreado. */
function ServicioCard({ servicio }: { servicio: SistemaServicio }) {
  const Icon = SERVICIO_ICONO[servicio.key] ?? Activity
  const color = ESTADO_META[servicio.status].color
  return (
    <div className="glass-card rounded-2xl p-5">
      <div className="flex items-start justify-between gap-2">
        <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: `${color}1A` }}>
          <Icon className="w-5 h-5" style={{ color }} />
        </div>
        <EstadoBadge status={servicio.status} />
      </div>
      <p className="text-base font-semibold text-gray-900 mt-3">{servicio.label}</p>
      <p className="text-sm text-gray-500 mt-0.5">
        {servicio.latency_ms != null
          ? `Latencia: ${servicio.latency_ms.toLocaleString('es-MX', { maximumFractionDigits: 1 })} ms`
          : servicio.detail ?? '—'}
      </p>
      {servicio.latency_ms != null && servicio.detail && (
        <p className="text-xs text-gray-400 mt-0.5">{servicio.detail}</p>
      )}
    </div>
  )
}

/** Una cifra de la cola de PDFs. */
function ColaStat({ label, value, alerta = false }: { label: string; value: number; alerta?: boolean }) {
  const color = alerta ? (value > 0 ? '#C0392B' : '#2E7D5B') : undefined
  return (
    <div className="rounded-xl px-4 py-3 text-center"
      style={{ background: alerta && value > 0 ? 'rgba(192,57,43,0.10)' : 'rgba(255,255,255,0.45)' }}>
      <p className="text-2xl font-bold" style={{ color: color ?? '#111827' }}>{value.toLocaleString('es-MX')}</p>
      <p className="text-xs text-gray-500 mt-0.5">{label}</p>
    </div>
  )
}

export default function SistemaPage() {
  const navigate = useNavigate()
  const { data, isLoading, isError, isFetching, refetch } = usePlatformSistema()

  const banner = data ? ESTADO_META[data.overall_status] : null

  return (
    <PlatformLayout active="sistema">
      <div className="glass-card rounded-2xl px-6 py-5">
        <h1 className="text-2xl font-bold text-gray-900">Salud del sistema</h1>
        <p className="text-sm text-gray-500">Estado en vivo de los servicios de la plataforma (se actualiza cada 30 s)</p>
      </div>

      {isError && (
        <div className="glass-card rounded-2xl py-10 px-6 flex items-center justify-center gap-3">
          <AlertCircle className="w-5 h-5 text-red-500 shrink-0" />
          <p className="text-sm text-red-600">No se pudo consultar la salud del sistema. ¿Tienes permiso para verla?</p>
        </div>
      )}

      {isLoading && !isError && (
        <div className="flex items-center justify-center gap-2 py-16 text-amber-700">
          <Loader2 className="w-5 h-5 animate-spin" /> Consultando servicios…
        </div>
      )}

      {!isLoading && !isError && data && banner && (
        <>
          {/* Banner de estado general */}
          <div className="glass-card rounded-2xl px-6 py-5 flex flex-wrap items-center gap-4"
            style={{ boxShadow: `inset 4px 0 0 ${banner.color}` }}>
            <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0" style={{ background: `${banner.color}1A` }}>
              <banner.Icon className="w-6 h-6" style={{ color: banner.color }} />
            </div>
            <div className="flex-1 min-w-[200px]">
              <p className="text-lg font-semibold" style={{ color: banner.color }}>{BANNER_TEXTO[data.overall_status]}</p>
              <p className="text-xs text-gray-500 mt-0.5">Actualizado {hace(data.generated_at)}</p>
            </div>
            <button onClick={() => { void refetch() }} disabled={isFetching}
              className="btn-secondary inline-flex items-center gap-1.5 text-xs py-2 px-3 disabled:opacity-40">
              <RefreshCw className={`w-4 h-4 ${isFetching ? 'animate-spin' : ''}`} />
              {isFetching ? 'Actualizando…' : 'Refrescar'}
            </button>
          </div>

          {/* Servicios */}
          <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
            {data.services.map(s => <ServicioCard key={s.key} servicio={s} />)}
          </div>
          {data.services.length === 0 && (
            <div className="glass-card rounded-2xl py-10 px-6 text-center">
              <Activity className="w-8 h-8 mx-auto mb-2 text-gray-300" />
              <p className="text-sm text-gray-400">El monitoreo no reportó servicios.</p>
            </div>
          )}

          <div className="grid gap-5 md:grid-cols-2">
            {/* Cola de PDFs */}
            <div className="glass-card rounded-2xl overflow-hidden">
              <div className="px-6 py-4 border-b border-white/50 flex items-center gap-2">
                <FileText className="w-4 h-4 text-gray-500" />
                <h2 className="text-base font-semibold text-gray-800">Cola de PDFs</h2>
              </div>
              <div className="grid grid-cols-3 gap-3 p-5">
                <ColaStat label="Pendientes" value={data.pdf_queue.pending} />
                <ColaStat label="Procesando" value={data.pdf_queue.processing} />
                <ColaStat label="Fallidos (24 h)" value={data.pdf_queue.failed_24h} alerta />
              </div>
              {data.pdf_queue.failed_24h > 0 && (
                <p className="px-6 pb-4 -mt-1 text-xs flex items-center gap-1.5" style={{ color: '#B45309' }}>
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                  Hay PDFs fallidos en las últimas 24 horas; revisa el worker.
                </p>
              )}
            </div>

            {/* Versión */}
            <div className="glass-card rounded-2xl overflow-hidden">
              <div className="px-6 py-4 border-b border-white/50 flex items-center gap-2">
                <Package className="w-4 h-4 text-gray-500" />
                <h2 className="text-base font-semibold text-gray-800">Versión</h2>
              </div>
              <div className="px-6 py-3 space-y-2.5 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-gray-500">Commit</span>
                  <span className="font-mono text-gray-800">{data.version.commit ? data.version.commit.slice(0, 7) : '—'}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-gray-500">Django</span>
                  <span className="text-gray-800">{data.version.django}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-gray-500">Python</span>
                  <span className="text-gray-800">{data.version.python}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-gray-500">Entorno</span>
                  <span className="text-gray-800">{data.version.environment}</span>
                </div>
              </div>
            </div>
          </div>

          {/* Incidentes → bitácora real en Auditoría (nada inventado) */}
          <button onClick={() => navigate('/plataforma/auditoria')}
            className="glass-card rounded-2xl px-6 py-4 w-full flex items-center gap-3 text-left transition-colors hover:bg-white/40">
            <ScrollText className="w-5 h-5 text-gray-500 shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-gray-800">Incidentes y actividad</p>
              <p className="text-xs text-gray-500">Consulta la bitácora completa en Auditoría</p>
            </div>
            <ArrowRight className="w-4 h-4 text-gray-400 shrink-0" />
          </button>
        </>
      )}
    </PlatformLayout>
  )
}
