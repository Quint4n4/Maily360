import { useMemo, useState } from 'react'
import {
  BarChart3,
  Wallet,
  FileText,
  Receipt,
  Lock,
  LineChart,
  CalendarClock,
  HeartHandshake,
} from 'lucide-react'

import Topbar from '../components/Topbar'
import DashboardTab from '../components/finanzas/DashboardTab'
import ReporteTab from '../components/finanzas/ReporteTab'
import CierreDiarioTab from '../components/finanzas/CierreDiarioTab'
import CobrosPagosTab from '../components/finanzas/CobrosPagosTab'
import CfdiTab from '../components/finanzas/CfdiTab'
import EstadoCuentaTab from '../components/finanzas/EstadoCuentaTab'
import RetencionTab from '../components/finanzas/RetencionTab'
import { can, canAccessFinance, type FinanceCapability } from '../auth/permisos'
import { ALL_ROLES, useRole } from '../auth/useRole'
import { toIsoDate } from '../lib/format'

type TabKey =
  | 'dashboard'
  | 'reportes'
  | 'cierre'
  | 'cobros'
  | 'cfdi'
  | 'estado'
  | 'retencion'

interface TabDef {
  key: TabKey
  label: string
  icon: typeof BarChart3
  capability: FinanceCapability
}

const TABS: TabDef[] = [
  { key: 'dashboard', label: 'Dashboard', icon: BarChart3, capability: 'viewDashboard' },
  { key: 'reportes', label: 'Reportes', icon: LineChart, capability: 'viewDashboard' },
  // Cierre diario = caja: misma matriz que registerPayment (owner/admin/finance/reception).
  { key: 'cierre', label: 'Cierre diario', icon: CalendarClock, capability: 'registerPayment' },
  { key: 'cobros', label: 'Cobros y pagos', icon: Wallet, capability: 'viewModule' },
  { key: 'cfdi', label: 'CFDI', icon: FileText, capability: 'viewCfdi' },
  { key: 'estado', label: 'Estado de cuenta', icon: Receipt, capability: 'viewStatement' },
  // Retención (RFM, Fase 3): misma matriz que el dashboard (owner/admin/finance/readonly).
  { key: 'retencion', label: 'Retención', icon: HeartHandshake, capability: 'viewDashboard' },
]

const RANGE_PRESETS = [
  { label: '7 días', days: 7 },
  { label: '30 días', days: 30 },
  { label: '90 días', days: 90 },
]

const GOLD = '#C9A227'

export default function FinanzasPage() {
  const { role, setRole } = useRole()
  const [activeTab, setActiveTab] = useState<TabKey>('dashboard')
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
    <div className="min-h-screen" style={{ background: 'linear-gradient(135deg, #f6f1e4 0%, #faf7ef 100%)' }}>
      <Topbar active="finanzas" />

      <main className="max-w-7xl mx-auto px-4 md:px-6 py-6 space-y-5">
        {/* Encabezado */}
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight" style={{ color: '#2A241B' }}>Finanzas</h1>
            <p className="text-sm" style={{ color: '#7A756C' }}>
              Cobros, cotizaciones, facturación CFDI 4.0 y analítica de tu clínica.
            </p>
          </div>

          {/* Selector de rol (demo de UX por rol — se reemplaza por la sesión real) */}
          <div className="flex items-center gap-2">
            <span className="text-xs" style={{ color: '#9A958C' }}>Vista de rol:</span>
            <select
              className="input py-1.5 text-sm"
              value={role}
              onChange={(e) => setRole(e.target.value as never)}
            >
              {ALL_ROLES.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </div>
        </div>

        {!canAccessFinance(role) ? (
          <div className="glass-card rounded-2xl p-10 text-center">
            <Lock className="w-8 h-8 mx-auto mb-3" style={{ color: '#9A958C' }} />
            <p className="text-sm" style={{ color: '#7A756C' }}>
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
                      className="flex items-center gap-2 px-3.5 py-2 rounded-xl text-sm font-medium transition-colors"
                      style={{
                        background: isActive ? 'rgba(201,162,39,0.16)' : 'rgba(255,255,255,0.5)',
                        color: isActive ? GOLD : '#7A756C',
                        border: isActive ? `1px solid ${GOLD}55` : '1px solid transparent',
                      }}
                    >
                      <Icon className="w-4 h-4" />
                      {label}
                    </button>
                  )
                })}
              </div>

              {current?.key === 'dashboard' && (
                <div className="flex items-center gap-1 rounded-lg p-0.5" style={{ background: 'rgba(0,0,0,0.04)' }}>
                  {RANGE_PRESETS.map((p) => (
                    <button
                      key={p.days}
                      onClick={() => setRangeDays(p.days)}
                      className="px-2.5 py-1 rounded-md text-xs font-medium transition-colors"
                      style={{
                        background: rangeDays === p.days ? GOLD : 'transparent',
                        color: rangeDays === p.days ? '#fff' : '#7A756C',
                      }}
                    >
                      {p.label}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Contenido */}
            {current?.key === 'dashboard' && (
              <DashboardTab range={range} onNavigate={(t) => setActiveTab(t as TabKey)} />
            )}
            {current?.key === 'reportes' && <ReporteTab role={role} />}
            {current?.key === 'cierre' && <CierreDiarioTab role={role} />}
            {current?.key === 'cobros' && <CobrosPagosTab role={role} />}
            {current?.key === 'cfdi' && <CfdiTab role={role} />}
            {current?.key === 'estado' && <EstadoCuentaTab />}
            {current?.key === 'retencion' && <RetencionTab role={role} />}
          </>
        )}
      </main>
    </div>
  )
}
