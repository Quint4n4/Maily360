/**
 * lib/exportReporte — exporta el reporte financiero de periodo a Excel (ExcelJS).
 *
 * El PDF del reporte lo genera el BACKEND (GET /finanzas/reporte/pdf/), así que
 * aquí solo construimos el .xlsx en el cliente a partir del dataset PeriodReport
 * que ya devuelve la API. Una hoja por bloque: Resumen, Serie, Métodos, Servicios,
 * Doctores, Aging. Decisión D-8 del plan: ExcelJS (no xlsx/SheetJS).
 */

import ExcelJS from 'exceljs'

import type { PeriodReport } from '../api/finanzas'

const GOLD_HEX = 'FFC9A227'
const MONEY_FMT = '$#,##0.00'
const PCT_FMT = '0.0%'

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

/** Aplica estilo de encabezado de marca (dorado + texto blanco) a la primera fila. */
function styleHeader(sheet: ExcelJS.Worksheet): void {
  const row = sheet.getRow(1)
  row.font = { bold: true, color: { argb: 'FFFFFFFF' } }
  row.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: GOLD_HEX } }
}

/** Convierte un valor que puede venir como string decimal de DRF a number seguro. */
function num(value: number | string | null | undefined): number {
  if (value === null || value === undefined || value === '') return 0
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(n) ? n : 0
}

/**
 * Genera y descarga el reporte de periodo como hoja de cálculo (.xlsx).
 * Refleja los campos EXACTOS de finance_period_report (production, collection,
 * collection_pct, ar_total, average_ticket, by_method/by_service/by_doctor, series,
 * aging). Async porque ExcelJS.writeBuffer es asíncrono.
 */
export async function exportReportExcel(report: PeriodReport): Promise<void> {
  const workbook = new ExcelJS.Workbook()

  // ── Hoja: Resumen ──────────────────────────────────────────────────────────
  const resumen = workbook.addWorksheet('Resumen')
  resumen.columns = [
    { header: 'Métrica', key: 'k', width: 32 },
    { header: 'Periodo actual', key: 'v', width: 20 },
    { header: 'Periodo anterior', key: 'p', width: 20 },
  ]
  styleHeader(resumen)
  resumen.addRow({
    k: 'Rango',
    v: `${report.range.date_from} a ${report.range.date_to}`,
    p: `${report.prev_range.date_from} a ${report.prev_range.date_to}`,
  })
  const moneyRow = (k: string, v: number, p: number): void => {
    const row = resumen.addRow({ k, v, p })
    row.getCell('v').numFmt = MONEY_FMT
    row.getCell('p').numFmt = MONEY_FMT
  }
  moneyRow('Producción', num(report.production), num(report.prev_production))
  moneyRow('Cobranza', num(report.collection), num(report.prev_collection))
  const pctRow = resumen.addRow({
    k: '% Cobranza',
    v: num(report.collection_pct),
    p: num(report.prev_collection_pct),
  })
  pctRow.getCell('v').numFmt = PCT_FMT
  pctRow.getCell('p').numFmt = PCT_FMT
  const arRow = resumen.addRow({ k: 'Cuentas por cobrar (A/R total)', v: num(report.ar_total), p: '' })
  arRow.getCell('v').numFmt = MONEY_FMT
  const ticketRow = resumen.addRow({ k: 'Ticket promedio', v: num(report.average_ticket), p: '' })
  ticketRow.getCell('v').numFmt = MONEY_FMT
  resumen.addRow({ k: 'Nº de cargos', v: num(report.charges_count), p: '' })
  const adjRow = resumen.addRow({ k: 'Ajustes', v: num(report.adjustments_total), p: '' })
  adjRow.getCell('v').numFmt = MONEY_FMT

  // ── Hoja: Serie temporal ─────────────────────────────────────────────────────
  const serie = workbook.addWorksheet('Serie')
  serie.columns = [
    { header: 'Periodo', key: 'period', width: 16 },
    { header: 'Producción', key: 'production', width: 16, style: { numFmt: MONEY_FMT } },
    { header: 'Cobranza', key: 'collection', width: 16, style: { numFmt: MONEY_FMT } },
  ]
  styleHeader(serie)
  for (const pt of report.series) {
    serie.addRow({
      period: pt.period,
      production: num(pt.production),
      collection: num(pt.collection),
    })
  }

  // ── Hoja: Métodos de pago ────────────────────────────────────────────────────
  const metodos = workbook.addWorksheet('Métodos')
  metodos.columns = [
    { header: 'Método', key: 'label', width: 20 },
    { header: 'Importe', key: 'amount', width: 16, style: { numFmt: MONEY_FMT } },
    { header: 'Pagos', key: 'count', width: 10 },
  ]
  styleHeader(metodos)
  for (const m of report.by_method) {
    metodos.addRow({ label: m.label, amount: num(m.amount), count: num(m.count) })
  }

  // ── Hoja: Servicios ──────────────────────────────────────────────────────────
  const servicios = workbook.addWorksheet('Servicios')
  servicios.columns = [
    { header: 'Servicio', key: 'name', width: 36 },
    { header: 'Importe', key: 'amount', width: 16, style: { numFmt: MONEY_FMT } },
    { header: 'Cargos', key: 'count', width: 10 },
  ]
  styleHeader(servicios)
  for (const s of report.by_service) {
    servicios.addRow({ name: s.name, amount: num(s.amount), count: num(s.count) })
  }

  // ── Hoja: Doctores ───────────────────────────────────────────────────────────
  const doctores = workbook.addWorksheet('Doctores')
  doctores.columns = [
    { header: 'Doctor', key: 'name', width: 36 },
    { header: 'Importe', key: 'amount', width: 16, style: { numFmt: MONEY_FMT } },
    { header: 'Cargos', key: 'count', width: 10 },
  ]
  styleHeader(doctores)
  for (const d of report.by_doctor) {
    doctores.addRow({ name: d.name, amount: num(d.amount), count: num(d.count) })
  }

  // ── Hoja: Antigüedad (A/R aging) ─────────────────────────────────────────────
  const aging = workbook.addWorksheet('Antigüedad')
  aging.columns = [
    { header: 'Rango (días)', key: 'bucket', width: 16 },
    { header: 'Saldo', key: 'amount', width: 16, style: { numFmt: MONEY_FMT } },
    { header: 'Cargos', key: 'count', width: 10 },
  ]
  styleHeader(aging)
  for (const a of report.aging) {
    aging.addRow({ bucket: a.bucket, amount: num(a.amount), count: num(a.count) })
  }

  const buffer = await workbook.xlsx.writeBuffer()
  const filename = `reporte-${report.range.date_from}-${report.range.date_to}.xlsx`
  triggerDownload(
    new Blob([buffer], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    }),
    filename,
  )
}
