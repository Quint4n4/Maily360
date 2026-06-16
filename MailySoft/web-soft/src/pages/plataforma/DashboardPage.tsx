import { Building2, Sparkles, Users, HeartPulse, Loader2, AlertCircle } from 'lucide-react'
import PlatformLayout from '../../platform/PlatformLayout'
import { ESTADO_CLINICA } from '../../data/clinicas'
import { usePlatformMetrics } from '../../hooks/plataforma'
import { formatMesAnio } from '../../lib/fecha'

export default function DashboardPlataformaPage() {
  const { data, isLoading, isError } = usePlatformMetrics()

  const porEstado = data?.clinicas_por_estado ?? {}
  const metricas = [
    { icon: Building2,  label: 'Clínicas activas',  valor: porEstado.active ?? 0,            color: '#2E7D5B' },
    { icon: Sparkles,   label: 'En prueba',         valor: porEstado.trial ?? 0,             color: '#C9A227' },
    { icon: HeartPulse, label: 'Pacientes totales', valor: data?.total_pacientes ?? 0,       color: '#3A6EA5' },
    { icon: Users,      label: 'Usuarios totales',  valor: data?.total_usuarios ?? 0,        color: '#7E57C2' },
  ]

  return (
    <PlatformLayout active="dashboard">
      <div className="glass-card rounded-2xl px-6 py-5">
        <h1 className="text-2xl font-bold text-gray-900">Panel de Maily</h1>
        <p className="text-sm text-gray-500">
          {isLoading ? 'Cargando…' : `Resumen general · ${data?.total_clinicas ?? 0} clínicas`}
        </p>
      </div>

      {isError && (
        <div className="glass-card rounded-2xl py-10 px-6 flex items-center justify-center gap-3">
          <AlertCircle className="w-5 h-5 text-red-500 shrink-0" />
          <p className="text-sm text-red-600">No se pudieron cargar las métricas.</p>
        </div>
      )}

      {isLoading && !isError && (
        <div className="flex items-center justify-center gap-2 py-16 text-amber-700">
          <Loader2 className="w-5 h-5 animate-spin" /> Cargando métricas…
        </div>
      )}

      {!isLoading && !isError && (
        <>
          {/* Métricas */}
          <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
            {metricas.map(({ icon: Icon, label, valor, color }) => (
              <div key={label} className="glass-card rounded-2xl p-5">
                <div className="w-10 h-10 rounded-xl flex items-center justify-center mb-3" style={{ background: `${color}1A` }}>
                  <Icon className="w-5 h-5" style={{ color }} />
                </div>
                <p className="text-2xl font-bold text-gray-900">{valor.toLocaleString('es-MX')}</p>
                <p className="text-sm text-gray-500 mt-0.5">{label}</p>
              </div>
            ))}
          </div>

          {/* Clínicas recientes */}
          <div className="glass-card rounded-2xl overflow-hidden">
            <div className="px-6 py-4 border-b border-white/50">
              <h2 className="text-base font-semibold text-gray-800">Clínicas recientes</h2>
            </div>
            {(data?.ultimas_clinicas ?? []).length === 0 ? (
              <p className="px-6 py-8 text-center text-sm text-gray-400">Aún no hay clínicas registradas.</p>
            ) : (
              (data?.ultimas_clinicas ?? []).map(c => {
                const e = ESTADO_CLINICA[c.status]
                return (
                  <div key={c.id} className="flex items-center justify-between px-6 py-3 border-b border-white/30">
                    <div className="flex items-center gap-3 min-w-0">
                      <div className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0" style={{ background: 'rgba(201,162,39,0.14)' }}>
                        <Building2 className="w-4 h-4" style={{ color: '#C9A227' }} />
                      </div>
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-gray-800 truncate">{c.name}</p>
                        <p className="text-xs text-gray-400">Desde {formatMesAnio(c.created_at)}</p>
                      </div>
                    </div>
                    <span className={`badge ${e.badge}`}>{e.label}</span>
                  </div>
                )
              })
            )}
          </div>
        </>
      )}
    </PlatformLayout>
  )
}
