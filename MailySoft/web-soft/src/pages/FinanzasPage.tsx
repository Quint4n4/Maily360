import { useMemo, useState } from 'react'
import { Wallet, Receipt, LineChart, FileText, Lock, type LucideIcon } from 'lucide-react'

import Topbar from '../components/Topbar'
import CajaTab from '../components/finanzas/CajaTab'
import CobranzaTab from '../components/finanzas/CobranzaTab'
import ResumenTab from '../components/finanzas/ResumenTab'
import CfdiTab from '../components/finanzas/CfdiTab'
import { can, canAccessFinance, type FinanceCapability } from '../auth/permisos'
import { useRole } from '../auth/RoleContext'
import { toIsoDate } from '../lib/format'

/*
 * Cuatro pantallas, una pregunta cada una, ordenadas por frecuencia de uso:
 * lo de todos los días primero, lo de cierre de mes al final.
 *
 * Antes eran siete y dos de ellas —"Dashboard" y "Reportes"— mostraban los
 * MISMOS cuatro KPIs calculados con la misma consulta, solo que con nombres
 * distintos ("Total facturado"/"Producción", "Ingresos"/"Cobranza"…). Se
 * comprobó contra datos reales: $60,220 y $36,390 en ambas.
 */
type TabKey = 'caja' | 'cobranza' | 'resumen' | 'facturacion'

interface TabDef {
  key: TabKey
  label: string
  icon: LucideIcon
  capability: FinanceCapability
  /** La pregunta que responde esta pantalla; se muestra como subtítulo. */
  pregunta: string
}

const TABS: TabDef[] = [
  // Todos los días: cobrar y cerrar caja. Es la pantalla de recepción.
  { key: 'caja', label: 'Caja', icon: Wallet, capability: 'viewModule',
    pregunta: '¿Qué cobro hoy y cómo cerró el día?' },
  // Cada pocos días: quién debe y desde cuándo.
  { key: 'cobranza', label: 'Cobranza', icon: Receipt, capability: 'viewStatement',
    pregunta: '¿Quién me debe y desde cuándo?' },
  // Semanal o al cierre de mes: la pantalla del dueño.
  { key: 'resumen', label: 'Resumen', icon: LineChart, capability: 'viewDashboard',
    pregunta: '¿Cómo va el negocio?' },
  // Cuando el paciente pide factura. Trabajo aparte, con reglas del SAT.
  { key: 'facturacion', label: 'Facturación', icon: FileText, capability: 'viewCfdi',
    pregunta: '¿Qué timbro?' },
]

const RANGE_PRESETS = [
  { label: '7 días', days: 7 },
  { label: '30 días', days: 30 },
  { label: '90 días', days: 90 },
]


export default function FinanzasPage() {
  const { role } = useRole()
  const [activeTab, setActiveTab] = useState<TabKey>('caja')
  const [rangeDays, setRangeDays] = useState(30)

  const range = useMemo(() => {
    const to = new Date()
    const from = new Date()
    from.setDate(from.getDate() - rangeDays)
    return { date_from: toIsoDate(from), date_to: toIsoDate(to) }
  }, [rangeDays])

  const visibleTabs = TABS.filter((t) => can(role, t.capability))
  const current = visibleTabs.find((t) => t.key === activeTab) ?? visibleTabs[0]

  return (
    <div className="min-h-screen relative">
      {/* Fondo plano: la foto de seda dorada quedaba DEBAJO de los datos
          (tablas, tarjetas, la reja de la agenda) y les restaba legibilidad. */}
      <div className="fixed inset-0 -z-10 bg-fondo" />
      <Topbar active="finanzas" />

      <main className="max-w-7xl mx-auto px-4 md:px-6 py-6 space-y-5">
        {/* Encabezado */}
        <div className="glass-card rounded-2xl px-6 py-5 flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-tinta">Finanzas</h1>
            {/* El subtítulo dice a qué vienes a esta pantalla, no qué contiene
                el módulo: la lista de features no ayuda a decidir dónde entrar. */}
            <p className="text-sm text-suave">{current?.pregunta}</p>
          </div>
        </div>

        {!canAccessFinance(role) ? (
          <div className="glass-card rounded-2xl p-10 text-center">
            <Lock className="w-8 h-8 mx-auto mb-3 text-tenue" />
            <p className="text-sm text-suave">
              Tu rol (<strong>{role}</strong>) no tiene acceso al módulo de finanzas.
            </p>
          </div>
        ) : (
          <>
            {/* Tabs + rango */}
            <div className="flex items-center justify-between flex-wrap gap-3">
              <div className="flex items-center gap-1 flex-wrap">
                {visibleTabs.map(({ key, label, icon: Icon }) => {
                  const isActive = current?.key === key
                  return (
                    <button
                      key={key}
                      onClick={() => setActiveTab(key)}
                      aria-current={isActive ? 'page' : undefined}
                      className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-sm font-medium transition-colors border ${
                        isActive
                          ? 'bg-accion text-white border-accion'
                          : 'bg-superficie text-suave border-borde hover:border-accion-borde hover:text-tinta'}`}
                    >
                      <Icon className="w-4 h-4" />
                      {label}
                    </button>
                  )
                })}
              </div>

              {current?.key === 'resumen' && (
                <div className="flex items-center gap-1 rounded-lg p-0.5 bg-superficie-sutil border border-borde">
                  {RANGE_PRESETS.map((p) => (
                    <button
                      key={p.days}
                      onClick={() => setRangeDays(p.days)}
                      className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                        rangeDays === p.days ? 'bg-accion text-white' : 'text-suave hover:text-tinta'}`}
                    >
                      {p.label}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Contenido */}
            {current?.key === 'caja' && <CajaTab role={role} />}
            {current?.key === 'cobranza' && <CobranzaTab role={role} />}
            {current?.key === 'resumen' && <ResumenTab role={role} range={range} />}
            {current?.key === 'facturacion' && <CfdiTab role={role} />}
          </>
        )}
      </main>
    </div>
  )
}
