/**
 * Helpers de fecha para la agenda. Trabajan en HORA LOCAL del navegador
 * (que en dev coincide con la zona de la clínica) y convierten a ISO/UTC al
 * hablar con el backend. Si en producción la clínica está en otra zona, esto
 * se centralizaría aquí.
 */

const MESES = [
  'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
  'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
]
const DIAS = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado']

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
const pad = (n: number) => (n < 10 ? `0${n}` : `${n}`)

/** 'yyyy-mm-dd' en hora local (clave estable para queries y caché). */
export function toDayKey(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** Parsea 'yyyy-mm-dd' a un Date local (mediodía, para evitar saltos por DST). */
export function fromDayKey(key: string): Date {
  const [y, m, d] = key.split('-').map(Number)
  return new Date(y, m - 1, d, 12, 0, 0, 0)
}

/** Rango UTC [inicio, fin] del día local, en ISO, para filtrar citas del día. */
export function dayRangeUTC(dayKey: string): { from: string; to: string } {
  const [y, m, d] = dayKey.split('-').map(Number)
  const start = new Date(y, m - 1, d, 0, 0, 0, 0)
  const end = new Date(y, m - 1, d, 23, 59, 59, 999)
  return { from: start.toISOString(), to: end.toISOString() }
}

/** Combina un día ('yyyy-mm-dd') + hora ('HH:MM') local → ISO UTC para el backend. */
export function combineToISO(dayKey: string, hhmm: string): string {
  const [y, m, d] = dayKey.split('-').map(Number)
  const [h, min] = hhmm.split(':').map(Number)
  return new Date(y, m - 1, d, h, min, 0, 0).toISOString()
}

/** Hora local {h, m} a partir de un ISO (UTC) del backend. */
export function localHM(iso: string): { h: number; m: number } {
  const d = new Date(iso)
  return { h: d.getHours(), m: d.getMinutes() }
}

/** 'HH:MM' local a partir de un ISO. */
export function localHHMM(iso: string): string {
  const { h, m } = localHM(iso)
  return `${h}:${pad(m)}`
}

/** "13:00" → "1:00 pm", "09:30" → "9:30 am" (formato 12h con am/pm). El valor
 *  real se conserva en 24h; esto es SOLO para mostrar. */
export function to12h(hhmm: string): string {
  const [h, m] = hhmm.split(':').map(Number)
  const h12 = h % 12 === 0 ? 12 : h % 12
  const ampm = h >= 12 ? 'pm' : 'am'
  return `${h12}:${pad(m)} ${ampm}`
}

/** Igual que localHHMM pero en formato 12h con am/pm (p. ej. "1:00 pm"). */
export function localHHMM12(iso: string): string {
  const { h, m } = localHM(iso)
  const h12 = h % 12 === 0 ? 12 : h % 12
  const ampm = h >= 12 ? 'pm' : 'am'
  return `${h12}:${pad(m)} ${ampm}`
}

/** Duración en minutos entre dos ISO. */
export function durationMin(startISO: string, endISO: string): number {
  return Math.max(0, Math.round((new Date(endISO).getTime() - new Date(startISO).getTime()) / 60000))
}

/** "Jueves 4 de Junio, 2026" */
export function formatLargo(d: Date): string {
  return `${cap(DIAS[d.getDay()])} ${d.getDate()} de ${cap(MESES[d.getMonth()])}, ${d.getFullYear()}`
}

/** "4 de Junio de 2026" */
export function formatMedio(d: Date): string {
  return `${d.getDate()} de ${cap(MESES[d.getMonth()])} de ${d.getFullYear()}`
}

/** "3 jun 2026" a partir de un ISO (solo fecha, mes abreviado). */
export function formatFechaCorta(iso: string): string {
  const d = new Date(iso)
  return `${d.getDate()} ${MESES[d.getMonth()].slice(0, 3)} ${d.getFullYear()}`
}

/** "Ene 2025" a partir de un ISO (mes abreviado + año). */
export function formatMesAnio(iso: string): string {
  const d = new Date(iso)
  return `${cap(MESES[d.getMonth()].slice(0, 3))} ${d.getFullYear()}`
}

/** "3 jun 2026 · 11:00" a partir de un ISO. */
export function formatFechaHora(iso: string): string {
  const d = new Date(iso)
  const mes = MESES[d.getMonth()].slice(0, 3)
  const h = d.getHours()
  const h12 = h % 12 === 0 ? 12 : h % 12
  const ampm = h >= 12 ? 'pm' : 'am'
  return `${d.getDate()} ${mes} ${d.getFullYear()} · ${h12}:${pad(d.getMinutes())} ${ampm}`
}

/** Suma días a una fecha (devuelve una nueva). */
export function addDays(d: Date, days: number): Date {
  const r = new Date(d)
  r.setDate(r.getDate() + days)
  return r
}

/** Suma meses a una fecha (devuelve una nueva). */
export function addMonths(d: Date, months: number): Date {
  const r = new Date(d)
  r.setMonth(r.getMonth() + months)
  return r
}

/** Suma un mes calendario recortando el día al último válido (31 ene → 28 feb).
 *  Espejo de _add_one_month del backend. */
export function addOneMonth(d: Date): Date {
  const r = new Date(d)
  const dia = r.getDate()
  r.setDate(1)
  r.setMonth(r.getMonth() + 1)
  const ultimo = new Date(r.getFullYear(), r.getMonth() + 1, 0).getDate()
  r.setDate(Math.min(dia, ultimo))
  return r
}

/** Genera las fechas de una serie por regla (espejo de _generate_series_starts).
 *  La primera es `start`. Tope por `count` (total) o `until` (inclusive). Máx 52. */
export function seriesDates(opts: {
  start: Date
  frequency: 'weekly' | 'biweekly' | 'monthly'
  count?: number | null
  until?: Date | null
}): Date[] {
  const MAX = 52
  const paso = (d: Date): Date =>
    opts.frequency === 'monthly'
      ? addOneMonth(d)
      : addDays(d, opts.frequency === 'biweekly' ? 14 : 7)
  const out: Date[] = [new Date(opts.start)]
  let cur = new Date(opts.start)
  while (out.length < MAX) {
    if (opts.count != null && out.length >= opts.count) break
    cur = paso(cur)
    if (opts.until != null && toDayKey(cur) > toDayKey(opts.until)) break
    out.push(new Date(cur))
  }
  return out
}

/** true si dos fechas son el mismo día calendario. */
export function sameDay(a: Date, b: Date): boolean {
  return toDayKey(a) === toDayKey(b)
}

/**
 * Celdas del mes que contiene `d`: arreglo de Dates (o null para huecos),
 * empezando en lunes. Útil para pintar la cuadrícula del calendario.
 */
export function monthGrid(d: Date): (Date | null)[] {
  const year = d.getFullYear()
  const month = d.getMonth()
  const first = new Date(year, month, 1)
  const lead = (first.getDay() + 6) % 7 // lunes = 0
  const daysInMonth = new Date(year, month + 1, 0).getDate()
  const cells: (Date | null)[] = []
  for (let i = 0; i < lead; i++) cells.push(null)
  for (let day = 1; day <= daysInMonth; day++) cells.push(new Date(year, month, day))
  while (cells.length % 7 !== 0) cells.push(null)
  return cells
}
