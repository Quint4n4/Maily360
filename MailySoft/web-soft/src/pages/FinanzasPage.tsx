<<<<<<< Updated upstream
=======
<<<<<<< HEAD
import { useMemo, useState } from 'react'
import {
  BarChart3,
  Wallet,
  FileText,
  Receipt,
  ScrollText,
  Lock,
} from 'lucide-react'

import Topbar from '../components/Topbar'
import DashboardTab from '../components/finanzas/DashboardTab'
import CobrosPagosTab from '../components/finanzas/CobrosPagosTab'
import CotizacionesTab from '../components/finanzas/CotizacionesTab'
import CfdiTab from '../components/finanzas/CfdiTab'
import EstadoCuentaTab from '../components/finanzas/EstadoCuentaTab'
import { can, canAccessFinance, type FinanceCapability } from '../auth/permisos'
import { ALL_ROLES, useRole } from '../auth/useRole'
import { toIsoDate } from '../lib/format'

type TabKey = 'dashboard' | 'cobros' | 'cotizaciones' | 'cfdi' | 'estado'

interface TabDef {
  key: TabKey
  label: string
  icon: typeof BarChart3
  capability: FinanceCapability
}

const TABS: TabDef[] = [
  { key: 'dashboard', label: 'Dashboard', icon: BarChart3, capability: 'viewDashboard' },
  { key: 'cobros', label: 'Cobros y pagos', icon: Wallet, capability: 'viewModule' },
  { key: 'cotizaciones', label: 'Cotizaciones', icon: ScrollText, capability: 'viewModule' },
  { key: 'cfdi', label: 'CFDI', icon: FileText, capability: 'viewCfdi' },
  { key: 'estado', label: 'Estado de cuenta', icon: Receipt, capability: 'viewStatement' },
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
            {current?.key === 'dashboard' && <DashboardTab range={range} />}
            {current?.key === 'cobros' && <CobrosPagosTab role={role} />}
            {current?.key === 'cotizaciones' && <CotizacionesTab role={role} />}
            {current?.key === 'cfdi' && <CfdiTab role={role} />}
            {current?.key === 'estado' && <EstadoCuentaTab />}
          </>
        )}
      </main>
=======
>>>>>>> Stashed changes
import { CircleDollarSign, TrendingUp, Clock, Receipt, Plus } from 'lucide-react'
import Topbar from '../components/Topbar'
import { useRole } from '../auth/RoleContext'
import { puedeEditar } from '../auth/permisos'

interface Cuenta {
  paciente: string
  concepto: string
  monto: number
  estado: 'Pagada' | 'Pendiente' | 'Vencida'
}

const CUENTAS: Cuenta[] = [
  { paciente: 'María González',  concepto: 'Terapia regenerativa — sesión 1', monto: 4500, estado: 'Pagada' },
  { paciente: 'Roberto Sánchez', concepto: 'Consulta subsecuente',             monto: 800,  estado: 'Pendiente' },
  { paciente: 'Lucía Ramírez',   concepto: 'Valoración inicial',               monto: 1200, estado: 'Pagada' },
  { paciente: 'Jorge Mendoza',   concepto: 'Aplicación PRP',                    monto: 6500, estado: 'Vencida' },
  { paciente: 'Daniela Torres',  concepto: 'Consulta de seguimiento',          monto: 800,  estado: 'Pendiente' },
]

const ESTADO_BADGE: Record<string, string> = {
  'Pagada':    'badge-success',
  'Pendiente': 'badge-warning',
  'Vencida':   'badge-danger',
}

const mxn = (n: number) => n.toLocaleString('es-MX', { style: 'currency', currency: 'MXN', minimumFractionDigits: 0 })

const METRICAS = [
  { icon: TrendingUp,        label: 'Ingresos del mes',  valor: mxn(86500), color: '#2E7D5B' },
  { icon: Clock,             label: 'Por cobrar',        valor: mxn(8100),  color: '#C9A227' },
  { icon: CircleDollarSign,  label: 'Cobrado hoy',       valor: mxn(5700),  color: '#3A6EA5' },
  { icon: Receipt,           label: 'Cuentas vencidas',  valor: '1',        color: '#C0392B' },
]

export default function FinanzasPage() {
  const { role } = useRole()
  const editar = puedeEditar(role, 'finanzas')

  return (
    <div className="min-h-screen relative">
      <div className="fixed inset-0 -z-10" style={{ background: 'linear-gradient(135deg, #b89a52 0%, #d8c690 45%, #f1e8cf 100%)' }} />
      <div className="fixed inset-0 -z-10 bg-cover bg-center" style={{ backgroundImage: "url('/fondo-agenda.jpg')" }} />
      <div className="fixed inset-0 -z-10" style={{ background: 'rgba(255,255,255,0.20)' }} />

      <Topbar active="finanzas" />

      <div className="p-5 max-w-[1300px] mx-auto space-y-5">

        {/* Cabecera */}
        <div className="glass-card rounded-2xl px-6 py-5 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Finanzas</h1>
            <p className="text-sm text-gray-500">Ingresos, cobros y cuentas por cobrar</p>
          </div>
          {editar && (
            <button className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110"
              style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}>
              <Plus className="w-4 h-4" /> Registrar pago
            </button>
          )}
        </div>

        {/* Métricas */}
        <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
          {METRICAS.map(({ icon: Icon, label, valor, color }) => (
            <div key={label} className="glass-card rounded-2xl p-5">
              <div className="w-10 h-10 rounded-xl flex items-center justify-center mb-3" style={{ background: `${color}1A` }}>
                <Icon className="w-5 h-5" style={{ color }} />
              </div>
              <p className="text-2xl font-bold text-gray-900">{valor}</p>
              <p className="text-sm text-gray-500 mt-0.5">{label}</p>
            </div>
          ))}
        </div>

        {/* Cuentas por cobrar */}
        <div className="glass-card rounded-2xl overflow-hidden">
          <div className="px-6 py-4 border-b border-white/50">
            <h2 className="text-base font-semibold text-gray-800">Cuentas por cobrar</h2>
          </div>

          <div className="grid items-center px-6 py-3 text-xs font-semibold text-gray-500 border-b border-white/40"
            style={{ gridTemplateColumns: '1.4fr 2fr 1fr 1fr 120px' }}>
            <span>Paciente</span><span>Concepto</span><span>Monto</span><span>Estado</span><span></span>
          </div>

          {CUENTAS.map((c, i) => (
            <div key={i} className="grid items-center px-6 py-3 border-b border-white/30"
              style={{ gridTemplateColumns: '1.4fr 2fr 1fr 1fr 120px' }}>
              <span className="text-sm font-medium text-gray-800">{c.paciente}</span>
              <span className="text-sm text-gray-600">{c.concepto}</span>
              <span className="text-sm font-semibold text-gray-800">{mxn(c.monto)}</span>
              <span><span className={`badge ${ESTADO_BADGE[c.estado]}`}>{c.estado}</span></span>
              <span className="text-right">
                {editar && c.estado !== 'Pagada' && (
                  <button className="text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors"
                    style={{ color: '#B8860B', background: 'rgba(201,162,39,0.12)' }}>
                    Cobrar
                  </button>
                )}
              </span>
            </div>
          ))}
        </div>

        {!editar && (
          <p className="text-center text-xs text-gray-500">Estás viendo Finanzas en modo solo lectura.</p>
        )}
      </div>
<<<<<<< Updated upstream
=======
>>>>>>> 9f3cd4149619be4d5c604a117d939f7904aad547
>>>>>>> Stashed changes
    </div>
  )
}
