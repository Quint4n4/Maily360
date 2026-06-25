/**
 * lib/exportEstadoCuenta — exporta el estado de cuenta de un paciente a PDF y Excel.
 *
 * El PDF usa jsPDF + autoTable (tabla de movimientos con totales).
 * El Excel usa ExcelJS (decisión D-8 del plan: ExcelJS sustituye a xlsx/SheetJS).
 * Ambos toman el AccountStatement que ya devuelve la API (api/finanzas.ts) y se
 * disparan desde EstadoCuentaTab.
 *
 * Nota: ExcelJS escribe a un ArrayBuffer (writeBuffer es async), así que el export
 * a Excel es asíncrono y dispara la descarga con un object URL temporal.
 */

import { jsPDF } from 'jspdf'
import autoTable from 'jspdf-autotable'
import ExcelJS from 'exceljs'

import type { AccountStatement } from '../api/finanzas'
import { formatDate, formatMoney } from './format'

const GOLD_HEX = 'FFC9A227'
const FOOT_HEX = 'FFF0E8CF'

function fileBase(statement: AccountStatement): string {
  const record = statement.patient?.record_number || statement.patient?.id || 'paciente'
  return `estado-cuenta-${record}`
}

/** Dispara la descarga de un Blob como archivo (object URL temporal). */
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

/** Genera y descarga el estado de cuenta como PDF. */
export function exportStatementPdf(statement: AccountStatement): void {
  const doc = new jsPDF({ unit: 'pt', format: 'a4' })

  doc.setFontSize(16)
  doc.text('Estado de cuenta', 40, 48)

  doc.setFontSize(10)
  doc.text(`Paciente: ${statement.patient?.full_name ?? ''}`, 40, 70)
  doc.text(`Expediente: ${statement.patient?.record_number ?? ''}`, 40, 84)

  autoTable(doc, {
    startY: 104,
    head: [['Fecha', 'Concepto', 'Cargo', 'Pago', 'Saldo', 'Referencia']],
    body: statement.movements.map((m) => [
      formatDate(m.date),
      m.description,
      m.charge ? formatMoney(m.charge) : '',
      m.payment ? formatMoney(m.payment) : '',
      formatMoney(m.balance),
      m.reference,
    ]),
    foot: [
      [
        'Totales',
        '',
        formatMoney(statement.total_charged),
        formatMoney(statement.total_paid),
        formatMoney(statement.balance),
        '',
      ],
    ],
    styles: { fontSize: 9 },
    headStyles: { fillColor: [201, 162, 39] },
    footStyles: { fillColor: [240, 232, 207], textColor: 20, fontStyle: 'bold' },
  })

  doc.save(`${fileBase(statement)}.pdf`)
}

/** Genera y descarga el estado de cuenta como hoja de cálculo (.xlsx) con ExcelJS. */
export async function exportStatementExcel(statement: AccountStatement): Promise<void> {
  const workbook = new ExcelJS.Workbook()
  const sheet = workbook.addWorksheet('Estado de cuenta')

  sheet.columns = [
    { header: 'Fecha', key: 'fecha', width: 16 },
    { header: 'Concepto', key: 'concepto', width: 36 },
    { header: 'Cargo', key: 'cargo', width: 14, style: { numFmt: '$#,##0.00' } },
    { header: 'Pago', key: 'pago', width: 14, style: { numFmt: '$#,##0.00' } },
    { header: 'Saldo', key: 'saldo', width: 14, style: { numFmt: '$#,##0.00' } },
    { header: 'Referencia', key: 'referencia', width: 20 },
  ]

  // Encabezado en negritas + relleno dorado de marca.
  const headerRow = sheet.getRow(1)
  headerRow.font = { bold: true, color: { argb: 'FFFFFFFF' } }
  headerRow.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: GOLD_HEX } }

  for (const m of statement.movements) {
    sheet.addRow({
      fecha: formatDate(m.date),
      concepto: m.description,
      // Montos como número real (no string) para que Excel los sume/formatee.
      cargo: m.charge || null,
      pago: m.payment || null,
      saldo: m.balance,
      referencia: m.reference,
    })
  }

  const totals = sheet.addRow({
    fecha: 'Totales',
    concepto: '',
    cargo: statement.total_charged,
    pago: statement.total_paid,
    saldo: statement.balance,
    referencia: '',
  })
  totals.font = { bold: true }
  totals.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: FOOT_HEX } }

  const buffer = await workbook.xlsx.writeBuffer()
  triggerDownload(
    new Blob([buffer], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    }),
    `${fileBase(statement)}.xlsx`,
  )
}
