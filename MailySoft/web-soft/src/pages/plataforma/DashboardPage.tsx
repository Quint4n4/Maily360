import { Building2, Sparkles, TrendingUp, Users } from 'lucide-react'
import PlatformLayout from '../../platform/PlatformLayout'
import { CLINICAS, ESTADO_CLINICA, mxn } from '../../data/clinicas'

const activas = CLINICAS.filter(c => c.estado === 'active').length
const enPrueba = CLINICAS.filter(c => c.estado === 'trial').length
const mrr = CLINICAS.reduce((s, c) => s + c.ingresoMensual, 0)
const usuarios = CLINICAS.reduce((s, c) => s + c.usuarios, 0)

const METRICAS = [
  { icon: Building2,   label: 'Clínicas activas',   valor: String(activas),  color: '#2E7D5B' },
  { icon: Sparkles,    label: 'En prueba',          valor: String(enPrueba), color: '#C9A227' },
  { icon: TrendingUp,  label: 'Ingreso mensual (MRR)', valor: mxn(mrr),      color: '#3A6EA5' },
  { icon: Users,       label: 'Usuarios totales',   valor: String(usuarios), color: '#7E57C2' },
]

export default function DashboardPlataformaPage() {
  const recientes = [...CLINICAS].slice(0, 5)

  return (
    <PlatformLayout active="dashboard">
      <div className="glass-card rounded-2xl px-6 py-5">
        <h1 className="text-2xl font-bold text-gray-900">Panel de Maily</h1>
        <p className="text-sm text-gray-500">Resumen general de todas las clínicas</p>
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

      {/* Clínicas recientes */}
      <div className="glass-card rounded-2xl overflow-hidden">
        <div className="px-6 py-4 border-b border-white/50">
          <h2 className="text-base font-semibold text-gray-800">Clínicas recientes</h2>
        </div>
        {recientes.map(c => {
          const e = ESTADO_CLINICA[c.estado]
          return (
            <div key={c.id} className="flex items-center justify-between px-6 py-3 border-b border-white/30">
              <div className="flex items-center gap-3 min-w-0">
                <div className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0" style={{ background: 'rgba(201,162,39,0.14)' }}>
                  <Building2 className="w-4 h-4" style={{ color: '#C9A227' }} />
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-gray-800 truncate">{c.nombre}</p>
                  <p className="text-xs text-gray-400">{c.ciudad} · Plan {c.plan}</p>
                </div>
              </div>
              <span className={`badge ${e.badge}`}>{e.label}</span>
            </div>
          )
        })}
      </div>
    </PlatformLayout>
  )
}
