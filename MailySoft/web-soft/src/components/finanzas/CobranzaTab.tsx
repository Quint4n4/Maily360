/**
 * Cobranza — «¿Quién me debe y desde cuándo?»
 *
 * El cambio de fondo respecto a la pestaña "Estado de cuenta" que sustituye:
 * antes había que ELEGIR un paciente para descubrir si debía algo. Eso solo
 * sirve si ya sospechas de alguien. La pregunta real de una clínica es la
 * inversa —quién debe— y esa no se podía responder sin ir paciente por paciente.
 *
 * Aquí se ve la cartera completa, ordenada por lo más vencido primero, que es
 * el orden en el que se cobra. El estado de cuenta individual no desaparece: se
 * abre al pulsar un renglón, y sigue estando dentro del expediente del paciente.
 *
 * Nota de implementación: no hay endpoint de "cartera por paciente", así que se
 * arma con los cargos pendientes/parciales agrupados en el cliente. Son dos
 * consultas cacheadas; si algún día la cartera crece mucho, esto debería pasar
 * al backend como un endpoint agregado.
 */

import { useMemo, useState } from 'react'
import { AlertTriangle, Loader2, Receipt, Search } from 'lucide-react'
import { useCharges } from '../../hooks/finanzas'
import { usePatients } from '../../hooks/pacientes'
import { formatMoney } from '../../lib/format'
import EstadoCuentaTab from './EstadoCuentaTab'
import SedeIndicador from './SedeIndicador'
import type { ClinicRole } from '../../auth/permisos'

/** Días transcurridos desde la emisión de un cargo. */
function diasDesde(iso: string): number {
  const emitido = new Date(iso).getTime()
  return Math.max(0, Math.floor((Date.now() - emitido) / 86_400_000))
}

/** Tramo de antigüedad al que pertenece un cargo. */
function tramo(dias: number): '0-30' | '31-60' | '61-90' | '90+' {
  if (dias <= 30) return '0-30'
  if (dias <= 60) return '31-60'
  if (dias <= 90) return '61-90'
  return '90+'
}

interface Deudor {
  patientId: string
  nombre: string
  saldo: number
  cargos: number
  /** Días del cargo MÁS ANTIGUO: es lo que define la urgencia. */
  diasMasViejo: number
}

const TRAMOS = ['0-30', '31-60', '61-90', '90+'] as const

export default function CobranzaTab({ role: _role }: { role: ClinicRole }) {
  const [busqueda, setBusqueda] = useState('')

  // Cargos con saldo abierto. El backend no permite pedir "pendiente O parcial"
  // en una sola llamada, así que son dos consultas (ambas cacheadas).
  const pendientes = useCharges({ status: 'pending' })
  const parciales = useCharges({ status: 'partial' })
  // Para resolver los nombres: el cargo solo trae el id del paciente.
  const pacientes = usePatients({})

  const cargando = pendientes.isLoading || parciales.isLoading || pacientes.isLoading
  const error = pendientes.isError || parciales.isError

  const nombrePorId = useMemo(() => {
    const m = new Map<string, string>()
    for (const p of pacientes.data?.results ?? []) m.set(p.id, p.full_name)
    return m
  }, [pacientes.data])

  const { deudores, porTramo, total } = useMemo(() => {
    const cargos = [...(pendientes.data?.results ?? []), ...(parciales.data?.results ?? [])]
    const porPaciente = new Map<string, Deudor>()
    const tramos: Record<string, number> = { '0-30': 0, '31-60': 0, '61-90': 0, '90+': 0 }
    let suma = 0

    for (const c of cargos) {
      const saldo = Number(c.balance) || 0
      if (saldo <= 0) continue
      const dias = diasDesde(c.issued_at)
      tramos[tramo(dias)] += saldo
      suma += saldo

      const previo = porPaciente.get(c.patient)
      if (previo) {
        previo.saldo += saldo
        previo.cargos += 1
        previo.diasMasViejo = Math.max(previo.diasMasViejo, dias)
      } else {
        porPaciente.set(c.patient, {
          patientId: c.patient,
          nombre: nombrePorId.get(c.patient) ?? 'Paciente',
          saldo,
          cargos: 1,
          diasMasViejo: dias,
        })
      }
    }

    // Lo más vencido primero: es el orden en el que se cobra.
    const lista = [...porPaciente.values()].sort((a, b) => b.diasMasViejo - a.diasMasViejo)
    return { deudores: lista, porTramo: tramos, total: suma }
  }, [pendientes.data, parciales.data, nombrePorId])

  const filtrados = busqueda.trim()
    ? deudores.filter(d => d.nombre.toLowerCase().includes(busqueda.trim().toLowerCase()))
    : deudores

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-end">
        <SedeIndicador />
      </div>

      {/* ── Cartera: el total y su antigüedad ───────────────────────────── */}
      <div className="card p-5">
        <p className="text-xs font-semibold uppercase tracking-wide text-suave">Total por cobrar</p>
        <p className="text-3xl font-bold text-tinta mt-1 tabular-nums">
          {cargando ? '—' : formatMoney(total)}
        </p>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 mt-4">
          {TRAMOS.map(t => {
            // Más de 90 días es dinero que probablemente ya no entra: se marca.
            const critico = t === '90+' && porTramo[t] > 0
            return (
              <div
                key={t}
                className={`rounded-xl px-3 py-2.5 border ${
                  critico ? 'bg-peligro-tinte border-peligro-borde' : 'bg-superficie-sutil border-borde'}`}
              >
                <p className={`text-[11px] font-semibold ${critico ? 'text-peligro' : 'text-suave'}`}>
                  {t === '90+' ? 'Más de 90 días' : `${t} días`}
                </p>
                <p className={`text-base font-bold tabular-nums ${critico ? 'text-peligro' : 'text-tinta'}`}>
                  {formatMoney(porTramo[t] ?? 0)}
                </p>
              </div>
            )
          })}
        </div>
      </div>

      {/* ── Quién debe ──────────────────────────────────────────────────── */}
      <div className="card overflow-hidden">
        <div className="flex items-center gap-3 px-4 py-3 border-b border-borde">
          <h3 className="text-sm font-semibold text-tinta shrink-0">
            Quién debe {!cargando && `(${deudores.length})`}
          </h3>
          <div className="relative flex-1 max-w-xs ml-auto">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-tenue pointer-events-none" />
            <input
              value={busqueda}
              onChange={e => setBusqueda(e.target.value)}
              placeholder="Buscar paciente…"
              className="input pl-8 py-1.5 text-xs"
            />
          </div>
        </div>

        {cargando && (
          <div className="flex items-center justify-center gap-2 py-10 text-sm text-accion">
            <Loader2 className="w-4 h-4 animate-spin" /> Cargando la cartera…
          </div>
        )}

        {error && !cargando && (
          <p className="py-10 text-center text-sm text-peligro">No se pudo cargar la cartera.</p>
        )}

        {!cargando && !error && filtrados.length === 0 && (
          <p className="py-10 text-center text-sm text-suave italic">
            {deudores.length === 0 ? 'Nadie tiene saldo pendiente.' : 'Ningún paciente coincide.'}
          </p>
        )}

        {!cargando && !error && filtrados.length > 0 && (
          <>
            <div className="hidden md:grid items-center gap-3 px-4 py-2 bg-superficie-sutil border-b border-borde
                            text-[10px] font-semibold uppercase tracking-wide text-suave"
              style={{ gridTemplateColumns: '1fr 7rem 8rem 7rem' }}>
              <span>Paciente</span>
              <span className="text-right">Cargos</span>
              <span className="text-right">Antigüedad</span>
              <span className="text-right">Saldo</span>
            </div>

            <div className="max-h-[22rem] overflow-y-auto">
              {filtrados.map((d, i) => {
                const vencido = d.diasMasViejo > 90
                return (
                  <div
                    key={d.patientId}
                    className="grid items-center gap-3 px-4 py-2.5 grid-cols-1 md:grid-cols-[1fr_7rem_8rem_7rem]"
                    style={{ borderTop: i === 0 ? 'none' : '1px solid var(--borde)' }}
                  >
                    <span className="text-sm font-semibold text-tinta truncate">{d.nombre}</span>
                    <span className="text-xs text-suave md:text-right pl-0 md:pl-0">
                      {d.cargos} {d.cargos === 1 ? 'cargo' : 'cargos'}
                    </span>
                    <span className={`text-xs md:text-right inline-flex items-center gap-1 md:justify-end ${
                      vencido ? 'text-peligro font-semibold' : 'text-suave'}`}>
                      {vencido && <AlertTriangle className="w-3 h-3 shrink-0" />}
                      {d.diasMasViejo} días
                    </span>
                    <span className={`text-sm font-bold tabular-nums md:text-right ${
                      vencido ? 'text-peligro' : 'text-tinta'}`}>
                      {formatMoney(d.saldo)}
                    </span>
                  </div>
                )
              })}
            </div>
          </>
        )}
      </div>

      {/* ── Estado de cuenta de un paciente concreto ─────────────────────── */}
      <div>
        <h3 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-suave mb-3">
          <Receipt className="w-4 h-4 text-borde-fuerte" /> Estado de cuenta de un paciente
        </h3>
        <EstadoCuentaTab />
      </div>
    </div>
  )
}
