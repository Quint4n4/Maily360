import { useMemo, useState } from 'react'
import { Loader2, FileDown, FileSpreadsheet } from 'lucide-react'

import type { ReportGroup } from '../../api/finanzas'
import { fetchReportPdfBlob } from '../../api/finanzas'
import { useReporte } from '../../hooks/finanzas'
import type { Role } from '../../auth/permisos'
import { can } from '../../auth/permisos'
import { toIsoDate } from '../../lib/format'
import { exportReportExcel } from '../../lib/exportReporte'
import VisorPdf from '../VisorPdf'
import ReporteKpiCards from './ReporteKpiCards'
import SerieTemporalChart from './charts/SerieTemporalChart'
import AgingApiladoChart from './charts/AgingApiladoChart'
import MetodosPagoChart from './charts/MetodosPagoChart'
import RankingBarChart from './charts/RankingBarChart'

interface Props {
  role: Role
}

const GOLD = '#C9A227'

/** Presets de rango: días hacia atrás + granularidad sugerida de la serie. */
interface RangePreset {
  key: string
  label: string
  days: number
  group: ReportGroup
}

const RANGE_PRESETS: RangePreset[] = [
  { key: 'day', label: 'Día', days: 1, group: 'day' },
  { key: 'week', label: 'Semana', days: 7, group: 'day' },
  { key: 'month', label: 'Mes', days: 30, group: 'day' },
  { key: 'year', label: 'Año', days: 365, group: 'month' },
]

const GROUPS: { key: ReportGroup; label: string }[] = [
  { key: 'day', label: 'Día' },
  { key: 'week', label: 'Semana' },
  { key: 'month', label: 'Mes' },
]

export default function ReporteTab({ role }: Props) {
  const [presetKey, setPresetKey] = useState('month')
  const [group, setGroup] = useState<ReportGroup>('day')

  const preset = RANGE_PRESETS.find((p) => p.key === presetKey) ?? RANGE_PRESETS[2]

  const params = useMemo(() => {
    const to = new Date()
    const from = new Date()
    from.setDate(from.getDate() - preset.days)
    return { date_from: toIsoDate(from), date_to: toIsoDate(to), group }
  }, [preset.days, group])

  const { data: report, isLoading, isError, error } = useReporte(params)
  const [verPdf, setVerPdf] = useState(false)
  const [excelBusy, setExcelBusy] = useState(false)

  // Gating de exportación: misma capacidad que ver el dashboard/reporte.
  const canExport = can(role, 'viewDashboard')

  const onPresetChange = (p: RangePreset): void => {
    setPresetKey(p.key)
    setGroup(p.group)
  }

  const onExportExcel = async (): Promise<void> => {
    if (!report) return
    setExcelBusy(true)
    try {
      await exportReportExcel(report)
    } finally {
      setExcelBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      {/* Barra de filtros + exportación */}
      <div className="glass-card rounded-2xl p-3 flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3 flex-wrap">
          {/* Rango */}
          <div className="flex items-center gap-1 rounded-lg p-0.5" style={{ background: 'rgba(0,0,0,0.04)' }}>
            {RANGE_PRESETS.map((p) => (
              <button
                key={p.key}
                onClick={() => onPresetChange(p)}
                className="px-2.5 py-1 rounded-md text-xs font-medium transition-colors"
                style={{
                  background: presetKey === p.key ? GOLD : 'transparent',
                  color: presetKey === p.key ? '#fff' : '#7A756C',
                }}
              >
                {p.label}
              </button>
            ))}
          </div>

          {/* Granularidad de la serie */}
          <div className="flex items-center gap-1.5">
            <span className="text-[11px]" style={{ color: '#9A958C' }}>Agrupar:</span>
            <div className="flex items-center gap-1 rounded-lg p-0.5" style={{ background: 'rgba(0,0,0,0.04)' }}>
              {GROUPS.map((g) => (
                <button
                  key={g.key}
                  onClick={() => setGroup(g.key)}
                  className="px-2.5 py-1 rounded-md text-xs font-medium transition-colors"
                  style={{
                    background: group === g.key ? GOLD : 'transparent',
                    color: group === g.key ? '#fff' : '#7A756C',
                  }}
                >
                  {g.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Exportación (solo roles con viewDashboard; el backend es la autoridad) */}
        {canExport && (
          <div className="flex items-center gap-2">
            <button
              className="btn-secondary"
              disabled={!report}
              onClick={() => setVerPdf(true)}
            >
              <FileDown className="w-4 h-4" />
              Exportar PDF
            </button>
            <button
              className="btn-secondary"
              disabled={!report || excelBusy}
              onClick={() => void onExportExcel()}
            >
              {excelBusy ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <FileSpreadsheet className="w-4 h-4" />
              )}
              Exportar Excel
            </button>
          </div>
        )}
      </div>

      {isLoading && (
        <div className="flex items-center justify-center py-20" style={{ color: '#9A958C' }}>
          <Loader2 className="w-6 h-6 animate-spin" />
        </div>
      )}

      {isError && (
        <div className="glass-card rounded-2xl p-6 text-sm" style={{ color: '#B91C1C' }}>
          No se pudo cargar el reporte financiero. {(error as Error)?.message ?? ''}
        </div>
      )}

      {report && (
        <>
          <ReporteKpiCards report={report} />

          <SerieTemporalChart report={report} />

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <AgingApiladoChart data={report.aging} />
            <MetodosPagoChart data={report.by_method} />
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <RankingBarChart
              title="Top servicios por producción"
              data={report.by_service.map((s) => ({ name: s.name, amount: s.amount, count: s.count }))}
              color="#7C3AED"
              countLabel="cargos"
              emptyLabel="Sin cargos en el periodo."
            />
            <RankingBarChart
              title="Producción por doctor"
              data={report.by_doctor.map((d) => ({ name: d.name, amount: d.amount, count: d.count }))}
              color="#1D4ED8"
              countLabel="cargos"
              emptyLabel="Sin producción atribuible a doctores."
            />
          </div>

          {report.adjustments_note && (
            <p className="text-[11px]" style={{ color: '#9A958C' }}>
              Nota: {report.adjustments_note}
            </p>
          )}
        </>
      )}

      {verPdf && (
        <VisorPdf
          titulo={`Reporte ${params.date_from} — ${params.date_to}`}
          nombreArchivo={`reporte-${params.date_from}-${params.date_to}.pdf`}
          cargar={() => fetchReportPdfBlob(params)}
          onClose={() => setVerPdf(false)}
        />
      )}
    </div>
  )
}
