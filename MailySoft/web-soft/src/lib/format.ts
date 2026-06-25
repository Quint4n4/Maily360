/**
 * lib/format — helpers de formato para el módulo Finanzas (es-MX / MXN).
 *
 * Centraliza el formateo de dinero, fechas y porcentajes para que toda la UI
 * de finanzas (KPIs, tablas, gráficas, estado de cuenta) se vea consistente.
 * Tolerante a entradas vacías/ inválidas: nunca lanza, devuelve un guion.
 */

const EMPTY = '—'

const moneyFmt = new Intl.NumberFormat('es-MX', {
  style: 'currency',
  currency: 'MXN',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const dateFmt = new Intl.DateTimeFormat('es-MX', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
})

const dateTimeFmt = new Intl.DateTimeFormat('es-MX', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

/** Convierte un valor que puede ser número o string numérico a number, o null. */
function toNumber(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(n) ? n : null
}

/** Formatea un monto en pesos mexicanos: 1234.5 → "$1,234.50". */
export function formatMoney(value: number | string | null | undefined): string {
  const n = toNumber(value)
  return n === null ? EMPTY : moneyFmt.format(n)
}

/** Formatea una fecha (ISO o Date) como "05 jun 2026". */
export function formatDate(value: string | Date | null | undefined): string {
  if (!value) return EMPTY
  const d = value instanceof Date ? value : new Date(value)
  return Number.isNaN(d.getTime()) ? EMPTY : dateFmt.format(d)
}

/** Formatea fecha y hora (ISO o Date) como "05 jun 2026, 14:30". */
export function formatDateTime(value: string | Date | null | undefined): string {
  if (!value) return EMPTY
  const d = value instanceof Date ? value : new Date(value)
  return Number.isNaN(d.getTime()) ? EMPTY : dateTimeFmt.format(d)
}

/**
 * Formatea un porcentaje. Acepta tanto fracción (0.42) como porcentaje (42):
 * un valor en [0, 1] se interpreta como fracción y se multiplica por 100.
 */
export function formatPercent(
  value: number | string | null | undefined,
  fractionDigits = 1,
): string {
  const n = toNumber(value)
  if (n === null) return EMPTY
  const pct = n > 0 && n <= 1 ? n * 100 : n
  return `${pct.toFixed(fractionDigits)}%`
}

/** Normaliza una fecha (ISO o Date) a 'yyyy-mm-dd' para query params. */
export function toIsoDate(value: string | Date | null | undefined): string {
  if (!value) return ''
  const d = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(d.getTime())) return ''
  const yyyy = d.getFullYear()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd}`
}
