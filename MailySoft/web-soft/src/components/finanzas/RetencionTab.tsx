/**
 * RetencionTab — Fase 3: Panel de retención de clientes (RFM). SOLO VISUALIZACIÓN.
 *
 * Decisión D-7 del plan: el sistema NO envía nada. Solo identifica y lista a los
 * pacientes que dejaron de venir (en riesgo / perdidos) para que la clínica los
 * contacte de forma MANUAL. Refleja 1:1 GET /api/v1/finanzas/retencion/.
 *
 * Gating de UX (no es seguridad): se monta solo si can(role, 'viewDashboard')
 * (owner/admin/finance/readonly). El backend (RetentionPermission) es la autoridad
 * y responde 403 a los demás roles.
 */

import { useState } from 'react'
import {
  Bar,
  BarChart,
  Cell,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Loader2, Lock, Download, Info, AlertTriangle, UserX } from 'lucide-react'

import type { Role } from '../../auth/permisos'
import { can } from '../../auth/permisos'
import { useRetencion } from '../../hooks/finanzas'
import type {
  RetentionActionablePatient,
  RetentionPanel,
  RetentionSegment,
} from '../../api/finanzas'
import { exportRetencionExcel } from '../../lib/exportRetencion'
import { formatMoney, formatPercent, formatDate } from '../../lib/format'
import SedeIndicador, { mensajeErrorSede } from './SedeIndicador'

interface Props {
  role: Role
}

const GOLD = '#C9A227'

/** Etiqueta y color por segmento (claves EXACTAS del backend). */
const SEGMENT_META: Record<RetentionSegment, { label: string; color: string; help: string }> = {
  nuevo: { label: 'Nuevos', color: '#2563EB', help: '1.ª visita en los últimos 90 días' },
  vip: { label: 'VIP', color: GOLD, help: 'Top 20% en gasto, recientes y frecuentes' },
  frecuente: { label: 'Frecuentes', color: '#0F766E', help: '≥2 visitas/año y vistos hace <6 meses' },
  ocasional: { label: 'Ocasionales', color: '#9A958C', help: 'Vienen de vez en cuando' },
  en_riesgo: { label: 'En riesgo', color: '#B45309', help: 'Eran regulares pero llevan >5 meses sin venir' },
  perdido: { label: 'Perdidos', color: '#B91C1C', help: 'Sin ninguna visita en los últimos 12 meses' },
}

/** Orden de presentación de los segmentos (de "bueno" a "perdido"). */
const SEGMENT_ORDER: RetentionSegment[] = [
  'nuevo',
  'vip',
  'frecuente',
  'ocasional',
  'en_riesgo',
  'perdido',
]

export default function RetencionTab({ role }: Props) {
  const { data, isLoading, isError, error } = useRetencion()
  const [exporting, setExporting] = useState(false)

  // Gating de UX: misma matriz que el dashboard (owner/admin/finance/readonly).
  // El backend es la autoridad y devuelve 403 a los demás.
  if (!can(role, 'viewDashboard')) {
    return (
      <div className="glass-card rounded-2xl p-10 text-center">
        <Lock className="w-8 h-8 mx-auto mb-3" style={{ color: '#9A958C' }} />
        <p className="text-sm" style={{ color: '#7A756C' }}>
          Tu rol (<strong>{role}</strong>) no tiene acceso al panel de retención de clientes.
        </p>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20" style={{ color: '#9A958C' }}>
        <Loader2 className="w-6 h-6 animate-spin" />
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="glass-card rounded-2xl p-6 text-sm" style={{ color: '#B91C1C' }}>
        {mensajeErrorSede(error, 'No se pudo cargar el panel de retención.')}
      </div>
    )
  }

  const handleExport = async (): Promise<void> => {
    setExporting(true)
    try {
      await exportRetencionExcel(data)
    } finally {
      setExporting(false)
    }
  }

  const segmentChartData = SEGMENT_ORDER.map((seg) => ({
    seg,
    label: SEGMENT_META[seg].label,
    color: SEGMENT_META[seg].color,
    count: data.segments[seg] ?? 0,
  }))

  return (
    <div className="space-y-4">
      {/* Sede del panel: la retención se calcula sobre la sede activa (o el
          consolidado de las sedes permitidas si eliges "Todas las sucursales"). */}
      <div className="flex items-center justify-end">
        <SedeIndicador />
      </div>

      {/* Aviso: solo visualización, contacto manual (D-7) */}
      <div
        className="rounded-xl p-3 flex items-start gap-2.5 text-xs"
        style={{ background: 'rgba(37,99,235,0.06)', border: '1px solid rgba(37,99,235,0.18)' }}
      >
        <Info className="w-4 h-4 mt-0.5 flex-shrink-0" style={{ color: '#2563EB' }} />
        <p style={{ color: '#34508A' }}>
          Este panel <strong>solo te muestra</strong> quién ha dejado de venir. No envía mensajes
          ni recordatorios automáticos: el contacto con cada paciente lo haces tú de forma{' '}
          <strong>manual</strong> (llamada, WhatsApp, etc.).
        </p>
      </div>

      {/* Fila de métricas */}
      <MetricsRow metrics={data.metrics} />

      {/* Distribución por segmento */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="xl:col-span-2">
          <SegmentChart data={segmentChartData} />
        </div>
        <SegmentLegendCards data={segmentChartData} />
      </div>

      {/* Botón exportar */}
      <div className="flex items-center justify-end">
        <button
          className="btn-secondary"
          onClick={handleExport}
          disabled={
            exporting ||
            (data.at_risk_list.length === 0 && data.lost_list.length === 0)
          }
        >
          {exporting ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Download className="w-4 h-4" />
          )}
          Exportar Excel
        </button>
      </div>

      {/* Listas accionables */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <ActionableList
          title="En riesgo"
          subtitle="Eran pacientes regulares pero llevan más de 5 meses sin venir."
          icon={AlertTriangle}
          tint="#B45309"
          patients={data.at_risk_list}
          total={data.total_at_risk}
          truncated={data.truncated}
        />
        <ActionableList
          title="Perdidos"
          subtitle="Sin ninguna visita en los últimos 12 meses."
          icon={UserX}
          tint="#B91C1C"
          patients={data.lost_list}
          total={data.total_lost}
          truncated={data.truncated}
        />
      </div>
    </div>
  )
}

/* ─── Métricas ─────────────────────────────────────────────────────────── */

function MetricsRow({ metrics }: { metrics: RetentionPanel['metrics'] }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      <MetricCard
        label="Tasa de retención"
        value={metrics.retention_rate === null ? '—' : formatPercent(metrics.retention_rate)}
        tint="#0F766E"
        hint={`${metrics.patients_seen_12m} vs ${metrics.patients_seen_prev_12m} pacientes`}
      />
      <MetricCard label="Ticket promedio" value={formatMoney(metrics.avg_ticket)} tint={GOLD} />
      <MetricCard
        label="Tasa de inasistencia"
        value={metrics.no_show_rate === null ? '—' : formatPercent(metrics.no_show_rate)}
        tint="#B45309"
      />
      <MetricCard
        label="Activos con próxima cita"
        value={
          metrics.pct_with_future_appt === null
            ? '—'
            : formatPercent(metrics.pct_with_future_appt)
        }
        tint="#2563EB"
      />
    </div>
  )
}

function MetricCard({
  label,
  value,
  tint,
  hint,
}: {
  label: string
  value: string
  tint: string
  hint?: string
}) {
  return (
    <div className="rounded-xl p-3" style={{ background: `${tint}10`, border: `1px solid ${tint}22` }}>
      <div className="text-[11px]" style={{ color: '#7A756C' }}>{label}</div>
      <div className="text-lg font-bold" style={{ color: tint }}>{value}</div>
      {hint && <div className="text-[10px] mt-0.5" style={{ color: '#9A958C' }}>{hint}</div>}
    </div>
  )
}

/* ─── Distribución por segmento ────────────────────────────────────────── */

interface SegmentDatum {
  seg: RetentionSegment
  label: string
  color: string
  count: number
}

function SegmentChart({ data }: { data: SegmentDatum[] }) {
  return (
    <div className="glass-card rounded-2xl p-4">
      <h3 className="text-sm font-semibold mb-3" style={{ color: '#2A241B' }}>
        Distribución de pacientes por segmento
      </h3>
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.06)" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fontSize: 11, fill: '#7A756C' }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            tick={{ fontSize: 11, fill: '#9A958C' }}
            axisLine={false}
            tickLine={false}
            width={40}
            allowDecimals={false}
          />
          <Tooltip
            formatter={(v: number) => [`${v} pacientes`, 'Total']}
            contentStyle={{ borderRadius: 12, border: '1px solid rgba(0,0,0,0.08)', fontSize: 12 }}
            cursor={{ fill: 'rgba(201,162,39,0.06)' }}
          />
          <Bar dataKey="count" radius={[6, 6, 0, 0]}>
            {data.map((entry) => (
              <Cell key={entry.seg} fill={entry.color} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function SegmentLegendCards({ data }: { data: SegmentDatum[] }) {
  return (
    <div className="glass-card rounded-2xl p-4">
      <h3 className="text-sm font-semibold mb-3" style={{ color: '#2A241B' }}>
        Resumen
      </h3>
      <div className="flex flex-col gap-2">
        {data.map((d) => (
          <div
            key={d.seg}
            className="flex items-center justify-between gap-2 rounded-lg px-2.5 py-1.5"
            style={{ background: `${d.color}0D` }}
          >
            <span className="flex items-center gap-2 text-xs">
              <span className="w-2.5 h-2.5 rounded-full" style={{ background: d.color }} />
              <span style={{ color: '#2A241B' }}>{d.label}</span>
            </span>
            <span className="text-sm font-bold" style={{ color: d.color }}>{d.count}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ─── Listas accionables ───────────────────────────────────────────────── */

interface ActionableListProps {
  title: string
  subtitle: string
  icon: typeof AlertTriangle
  tint: string
  patients: RetentionActionablePatient[]
  total: number
  truncated: boolean
}

const CAP = 500

function ActionableList({
  title,
  subtitle,
  icon: Icon,
  tint,
  patients,
  total,
  truncated,
}: ActionableListProps) {
  // "Mostrando 500 de N" solo cuando esta lista realmente se recortó.
  const isCapped = truncated && total > CAP

  return (
    <div className="glass-card rounded-2xl p-4">
      <div className="flex items-center justify-between mb-1">
        <h3 className="text-sm font-semibold flex items-center gap-2" style={{ color: '#2A241B' }}>
          <Icon className="w-4 h-4" style={{ color: tint }} />
          {title}
        </h3>
        <span
          className="px-2 py-0.5 rounded-full text-xs font-semibold"
          style={{ background: `${tint}14`, color: tint }}
        >
          {total}
        </span>
      </div>
      <p className="text-[11px] mb-3" style={{ color: '#9A958C' }}>
        {subtitle} Contáctalos tú mismo/a (manual).
      </p>

      {isCapped && (
        <p className="text-[11px] mb-2" style={{ color: '#B45309' }}>
          Mostrando {CAP} de {total}. Exporta a Excel para revisar a fondo.
        </p>
      )}

      <div className="overflow-auto max-h-[320px]">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left" style={{ color: '#9A958C' }}>
              <th className="py-1.5 font-medium">Paciente</th>
              <th className="py-1.5 font-medium">Contacto</th>
              <th className="py-1.5 font-medium">Última visita</th>
              <th className="py-1.5 font-medium text-right">Gasto 12m</th>
            </tr>
          </thead>
          <tbody>
            {patients.map((p) => (
              <tr key={p.patient_id} className="border-t" style={{ borderColor: 'rgba(0,0,0,0.05)' }}>
                <td className="py-1.5" style={{ color: '#2A241B' }}>{p.full_name || '—'}</td>
                <td className="py-1.5" style={{ color: '#7A756C' }}>
                  {p.phone || p.email || '—'}
                </td>
                <td className="py-1.5" style={{ color: '#7A756C' }}>
                  {p.last_visited ? formatDate(p.last_visited) : '—'}
                </td>
                <td className="py-1.5 text-right font-medium" style={{ color: '#2A241B' }}>
                  {formatMoney(p.spent_12m)}
                </td>
              </tr>
            ))}
            {patients.length === 0 && (
              <tr>
                <td colSpan={4} className="py-8 text-center" style={{ color: '#9A958C' }}>
                  Sin pacientes en este grupo. ¡Buena señal!
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
