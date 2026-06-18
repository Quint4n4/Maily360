import { useMemo, useState } from 'react'
import { Loader2 } from 'lucide-react'

import type { DateRangeParams } from '../../api/finanzas'
import { useCharges, useDashboard, usePayments } from '../../hooks/finanzas'
import { formatMoney, formatDate, formatDateTime } from '../../lib/format'
import KpiCards from './KpiCards'
import IngresosPeriodoChart from './charts/IngresosPeriodoChart'
import IngresosConceptoChart from './charts/IngresosConceptoChart'
import MetodosPagoChart from './charts/MetodosPagoChart'
import AgingChart from './charts/AgingChart'
import EmbudoChart from './charts/EmbudoChart'

interface Props {
  range: DateRangeParams
}

function bucketAgeDays(bucket: string, isoDate: string): boolean {
  const days = (Date.now() - new Date(isoDate).getTime()) / 86400000
  if (bucket === '0-30') return days <= 30
  if (bucket === '31-60') return days > 30 && days <= 60
  if (bucket === '61-90') return days > 60 && days <= 90
  return days > 90
}

export default function DashboardTab({ range }: Props) {
  const { data, isLoading, isError, error } = useDashboard(range)

  // Drill-down compartido entre las gráficas y la tabla de movimientos.
  const [selectedDate, setSelectedDate] = useState<string | null>(null)
  const [selectedConcept, setSelectedConcept] = useState<string | null>(null)
  const [selectedMethod, setSelectedMethod] = useState<string | null>(null)
  const [selectedBucket, setSelectedBucket] = useState<string | null>(null)

  // Datos para la tabla de drill-down.
  const payments = usePayments(selectedMethod ? { method: selectedMethod } : {})
  const charges = useCharges({})

  const drillRows = useMemo(() => {
    // Prioridad: bucket > concepto > método/fecha (pagos).
    if (selectedBucket) {
      const list = (charges.data?.results ?? []).filter(
        (c) =>
          (c.status === 'pending' || c.status === 'partial') &&
          bucketAgeDays(selectedBucket, c.issued_at),
      )
      return {
        title: `Cargos con antigüedad ${selectedBucket} días`,
        kind: 'charge' as const,
        rows: list.map((c) => ({
          id: c.id,
          a: formatDate(c.issued_at),
          b: c.description,
          c: formatMoney(c.balance),
        })),
      }
    }
    if (selectedConcept) {
      const list = (charges.data?.results ?? []).filter((c) => c.description === selectedConcept)
      return {
        title: `Movimientos del concepto «${selectedConcept}»`,
        kind: 'charge' as const,
        rows: list.map((c) => ({
          id: c.id,
          a: formatDate(c.issued_at),
          b: c.status_display,
          c: formatMoney(c.amount),
        })),
      }
    }
    // Pagos (filtrados por método y/o fecha).
    let list = payments.data?.results ?? []
    if (selectedDate) list = list.filter((p) => p.received_at.slice(0, 10) === selectedDate)
    return {
      title:
        selectedMethod || selectedDate
          ? 'Pagos filtrados'
          : 'Pagos recientes',
      kind: 'payment' as const,
      rows: list.slice(0, 12).map((p) => ({
        id: p.id,
        a: formatDateTime(p.received_at),
        b: p.method_display,
        c: formatMoney(p.amount),
      })),
    }
  }, [selectedBucket, selectedConcept, selectedDate, selectedMethod, charges.data, payments.data])

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
        No se pudo cargar el panel financiero. {(error as Error)?.message ?? ''}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <KpiCards kpis={data.kpis} />

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="xl:col-span-2">
          <IngresosPeriodoChart
            data={data.income_by_day}
            selectedDate={selectedDate}
            onSelectDate={(d) => {
              setSelectedDate(d)
              setSelectedConcept(null)
              setSelectedBucket(null)
            }}
          />
        </div>
        <MetodosPagoChart
          data={data.income_by_method}
          selectedMethod={selectedMethod}
          onSelectMethod={(m) => {
            setSelectedMethod(m)
            setSelectedConcept(null)
            setSelectedBucket(null)
          }}
        />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <IngresosConceptoChart
          data={data.income_by_concept}
          selectedConcept={selectedConcept}
          onSelectConcept={(c) => {
            setSelectedConcept(c)
            setSelectedBucket(null)
          }}
        />
        <AgingChart
          data={data.aging}
          selectedBucket={selectedBucket}
          onSelectBucket={(b) => {
            setSelectedBucket(b)
            setSelectedConcept(null)
          }}
        />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <EmbudoChart funnel={data.quotes_funnel} />

        {/* Tabla de drill-down ligada a las gráficas */}
        <div className="glass-card rounded-2xl p-4">
          <h3 className="text-sm font-semibold mb-3" style={{ color: '#2A241B' }}>
            {drillRows.title}
          </h3>
          <div className="overflow-auto max-h-[240px]">
            <table className="w-full text-xs">
              <thead>
                <tr style={{ color: '#9A958C' }} className="text-left">
                  <th className="py-1.5 font-medium">Fecha</th>
                  <th className="py-1.5 font-medium">
                    {drillRows.kind === 'payment' ? 'Método' : 'Detalle'}
                  </th>
                  <th className="py-1.5 font-medium text-right">Monto</th>
                </tr>
              </thead>
              <tbody>
                {drillRows.rows.map((r) => (
                  <tr key={r.id} className="border-t" style={{ borderColor: 'rgba(0,0,0,0.05)' }}>
                    <td className="py-1.5" style={{ color: '#7A756C' }}>{r.a}</td>
                    <td className="py-1.5" style={{ color: '#2A241B' }}>{r.b}</td>
                    <td className="py-1.5 text-right font-medium" style={{ color: '#2A241B' }}>{r.c}</td>
                  </tr>
                ))}
                {drillRows.rows.length === 0 && (
                  <tr>
                    <td colSpan={3} className="py-6 text-center" style={{ color: '#9A958C' }}>
                      Sin movimientos para este filtro.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
