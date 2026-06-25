/**
 * lib/exportRetencion — exporta las listas accionables de retención a Excel (ExcelJS).
 *
 * Fase 3 (RFM, D-7: SOLO VISUALIZACIÓN). El backend solo devuelve los pacientes
 * en_riesgo / perdidos para que la clínica los contacte de forma MANUAL. Este
 * módulo arma un .xlsx en el cliente con dos hojas (En riesgo, Perdidos) a partir
 * del dataset RetentionPanel que ya devuelve la API. Mismo patrón ExcelJS que
 * src/lib/exportReporte.ts (decisión D-8 del plan: ExcelJS, no xlsx/SheetJS).
 */

import ExcelJS from 'exceljs'

import type { RetentionActionablePatient, RetentionPanel } from '../api/finanzas'

const GOLD_HEX = 'FFC9A227'
const MONEY_FMT = '$#,##0.00'

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

/** Construye una hoja con la lista de pacientes accionables (nombre + contacto MANUAL). */
function buildSheet(
  workbook: ExcelJS.Workbook,
  title: string,
  patients: RetentionActionablePatient[],
): void {
  const sheet = workbook.addWorksheet(title)
  sheet.columns = [
    { header: 'Paciente', key: 'name', width: 32 },
    { header: 'Teléfono', key: 'phone', width: 18 },
    { header: 'Correo', key: 'email', width: 30 },
    { header: 'Última visita', key: 'last', width: 16 },
    { header: 'Días sin venir', key: 'recency', width: 14 },
    { header: 'Visitas 12m', key: 'freq', width: 12 },
    { header: 'Gasto 12m', key: 'spent', width: 16, style: { numFmt: MONEY_FMT } },
  ]
  styleHeader(sheet)
  for (const p of patients) {
    sheet.addRow({
      name: p.full_name,
      phone: p.phone,
      email: p.email,
      last: p.last_visited ?? '',
      recency: p.recency_days ?? '',
      freq: num(p.freq_12m),
      spent: num(p.spent_12m),
    })
  }
}

/**
 * Genera y descarga las listas accionables de retención como hoja de cálculo (.xlsx).
 * Refleja los campos EXACTOS de retention_panel_build (at_risk_list / lost_list:
 * full_name, phone, email, last_visited, recency_days, freq_12m, spent_12m).
 * Async porque ExcelJS.writeBuffer es asíncrono.
 */
export async function exportRetencionExcel(panel: RetentionPanel): Promise<void> {
  const workbook = new ExcelJS.Workbook()
  buildSheet(workbook, 'En riesgo', panel.at_risk_list)
  buildSheet(workbook, 'Perdidos', panel.lost_list)

  const buffer = await workbook.xlsx.writeBuffer()
  const today = new Date().toISOString().slice(0, 10)
  triggerDownload(
    new Blob([buffer], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    }),
    `retencion-pacientes-${today}.xlsx`,
  )
}
