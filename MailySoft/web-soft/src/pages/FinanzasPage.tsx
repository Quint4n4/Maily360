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
    </div>
  )
}
