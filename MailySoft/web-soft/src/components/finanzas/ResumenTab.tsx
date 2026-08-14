/**
 * Resumen — «¿Cómo va el negocio?»
 *
 * Sustituye a las dos pestañas que antes había, "Dashboard" y "Reportes". No se
 * fusionan por gusto: mostraban los MISMOS cuatro KPIs calculados con la misma
 * consulta, solo que con nombres distintos. Comprobado contra datos reales de
 * un tenant: producción $60,220 y cobranza $36,390 idénticos en ambas.
 *
 * El "Dashboard" era, de hecho, la versión pobre: enseñaba los mismos números
 * SIN la comparación contra el periodo anterior, que ya existía en el endpoint
 * del reporte. Al fusionar, esa comparación se gana gratis.
 *
 * Estructura: arriba tres números y UNA gráfica; todo el desglose vive tras
 * «Ver detalle». La distancia entre las dos líneas de esa gráfica —producción
 * contra cobranza— es el problema de cobranza dibujado, y es lo único que hay
 * que mirar a diario.
 */

import { useMemo, useState } from 'react'
import { ChevronDown, FileDown, FileSpreadsheet, Loader2 } from 'lucide-react'

import type { ReportGroup } from '../../api/finanzas'
import { fetchReportPdfBlob } from '../../api/finanzas'
import { useDashboard, useReporte } from '../../hooks/finanzas'
import type { Role } from '../../auth/permisos'
import { can } from '../../auth/permisos'
import { exportReportExcel } from '../../lib/exportReporte'
import VisorPdf from '../VisorPdf'
import ReporteKpiCards from './ReporteKpiCards'
import SedeIndicador, { mensajeErrorSede } from './SedeIndicador'
import SerieTemporalChart from './charts/SerieTemporalChart'
import AgingApiladoChart from './charts/AgingApiladoChart'
import MetodosPagoChart from './charts/MetodosPagoChart'
import RankingBarChart from './charts/RankingBarChart'
import EmbudoChart from './charts/EmbudoChart'
import RetencionTab from './RetencionTab'

interface Props {
  role: Role
  /** Rango elegido en la cabecera de Finanzas (7 / 30 / 90 días). */
  range: { date_from: string; date_to: string }
}

const GROUPS: { key: ReportGroup; label: string }[] = [
  { key: 'day', label: 'Día' },
  { key: 'week', label: 'Semana' },
  { key: 'month', label: 'Mes' },
]

export default function ResumenTab({ role, range }: Props) {
  const [group, setGroup] = useState<ReportGroup>('day')
  const [detalle, setDetalle] = useState(false)
  const [verPdf, setVerPdf] = useState(false)
  const [excelBusy, setExcelBusy] = useState(false)

  const params = useMemo(
    () => ({ date_from: range.date_from, date_to: range.date_to, group }),
    [range.date_from, range.date_to, group],
  )

  const { data: report, isLoading, isError, error } = useReporte(params)

  /*
   * El embudo de cotizaciones es lo único que el reporte NO trae y que sí vivía
   * en el panel viejo. Se pide solo al abrir el detalle para no gastar una
   * consulta entera del dashboard en cada visita a la pantalla.
   */
  const { data: panel } = useDashboard(
    { date_from: range.date_from, date_to: range.date_to },
    { enabled: detalle },
  )

  const canExport = can(role, 'viewDashboard')

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
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-suave">Agrupar:</span>
          <div className="flex items-center gap-1 rounded-lg p-0.5 bg-superficie-sutil border border-borde">
            {GROUPS.map((g) => (
              <button
                key={g.key}
                onClick={() => setGroup(g.key)}
                className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                  group === g.key ? 'bg-accion text-white' : 'text-suave hover:text-tinta'}`}
              >
                {g.label}
              </button>
            ))}
          </div>
        </div>
        <SedeIndicador />
      </div>

      {isLoading && (
        <div className="flex items-center justify-center py-20 text-accion">
          <Loader2 className="w-6 h-6 animate-spin" />
        </div>
      )}

      {isError && (
        <div className="card p-6 text-sm text-peligro">
          {mensajeErrorSede(error, 'No se pudo cargar el resumen financiero.')}
        </div>
      )}

      {report && (
        <>
          <ReporteKpiCards report={report} />

          {/* La única gráfica de la portada: producción contra cobranza. */}
          <SerieTemporalChart report={report} />

          {/* ── Todo el desglose, plegado ────────────────────────────────
              Son análisis de cierre de mes, no de vistazo diario. Dejarlos
              abiertos convertía esta pantalla en 2 pantallas de scroll. */}
          <button
            type="button"
            onClick={() => setDetalle(v => !v)}
            aria-expanded={detalle}
            className="w-full flex items-center gap-2 rounded-2xl px-4 py-3 bg-superficie border border-borde
                       hover:border-accion-borde hover:bg-accion-tinte transition-colors text-left"
          >
            <span className="flex-1 text-sm font-semibold text-tinta">Ver detalle</span>
            <span className="text-xs text-suave">
              Antigüedad · métodos de pago · servicios · doctores · pacientes en riesgo
            </span>
            <ChevronDown
              className={`w-4 h-4 shrink-0 text-suave transition-transform ${detalle ? 'rotate-180' : ''}`}
            />
          </button>

          {detalle && (
            <div className="space-y-4">
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <AgingApiladoChart data={report.aging} />
                <MetodosPagoChart data={report.by_method} />
              </div>

              {panel && (
                <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                  <EmbudoChart funnel={panel.quotes_funnel} />
                </div>
              )}

              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <RankingBarChart
                  title="Top servicios por producción"
                  data={report.by_service.map((s) => ({ name: s.name, amount: s.amount, count: s.count }))}
                  color="var(--accion)"
                  countLabel="cargos"
                  emptyLabel="Sin cargos en el periodo."
                />
                <RankingBarChart
                  title="Producción por doctor"
                  data={report.by_doctor.map((d) => ({ name: d.name, amount: d.amount, count: d.count }))}
                  color="var(--borde-fuerte)"
                  countLabel="cargos"
                  emptyLabel="Sin producción atribuible a doctores."
                />
              </div>

              {/* Retención: quién dejó de venir. Es ingreso en riesgo, así que
                  pertenece al resumen del negocio y no a una pestaña propia. */}
              <div>
                <h3 className="text-sm font-semibold uppercase tracking-wide text-suave mb-3">
                  Pacientes que dejaron de venir
                </h3>
                <RetencionTab role={role} />
              </div>

              {canExport && (
                <div className="flex items-center gap-2">
                  <button className="btn-secondary" disabled={!report} onClick={() => setVerPdf(true)}>
                    <FileDown className="w-4 h-4" /> Exportar PDF
                  </button>
                  <button
                    className="btn-secondary"
                    disabled={!report || excelBusy}
                    onClick={() => void onExportExcel()}
                  >
                    {excelBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileSpreadsheet className="w-4 h-4" />}
                    Exportar Excel
                  </button>
                </div>
              )}
            </div>
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
