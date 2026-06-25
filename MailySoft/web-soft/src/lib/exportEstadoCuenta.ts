/**
 * lib/exportEstadoCuenta — exporta el estado de cuenta de un paciente a PDF y Excel.
 *
 * El PDF usa jsPDF + autoTable (tabla de movimientos con totales).
 * El Excel usa SheetJS (xlsx). Ambos toman el AccountStatement que ya devuelve
 * la API (api/finanzas.ts) y se disparan desde EstadoCuentaTab.
 */

import { jsPDF } from 'jspdf'
import autoTable from 'jspdf-autotable'
import * as XLSX from 'xlsx'

import type { AccountStatement } from '../api/finanzas'
import { formatDate, formatMoney } from './format'

function fileBase(statement: AccountStatement): string {
  const record = statement.patient?.record_number || statement.patient?.id || 'paciente'
  return `estado-cuenta-${record}`
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

/** Genera y descarga el estado de cuenta como hoja de cálculo (.xlsx). */
export function exportStatementExcel(statement: AccountStatement): void {
  const rows = statement.movements.map((m) => ({
    Fecha: formatDate(m.date),
    Concepto: m.description,
    Cargo: m.charge || '',
    Pago: m.payment || '',
    Saldo: m.balance,
    Referencia: m.reference,
  }))

  rows.push({
    Fecha: 'Totales',
    Concepto: '',
    Cargo: statement.total_charged,
    Pago: statement.total_paid,
    Saldo: statement.balance,
    Referencia: '',
  })

  const worksheet = XLSX.utils.json_to_sheet(rows)
  const workbook = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(workbook, worksheet, 'Estado de cuenta')
  XLSX.writeFile(workbook, `${fileBase(statement)}.xlsx`)
}
