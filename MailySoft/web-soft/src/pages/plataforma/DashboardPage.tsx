import { Building2, Sparkles, Users, HeartPulse, Loader2, AlertCircle, AlertTriangle, ScrollText, ChevronRight } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import PlatformLayout from '../../platform/PlatformLayout'
import { ESTADO_CLINICA } from '../../data/clinicas'
import { usePlatformMetrics, usePlatformAuditoria, useSuscripcionesResumen } from '../../hooks/plataforma'
import { usePlatformRole } from '../../platform/PlatformRoleContext'
import { accesoModuloPlat } from '../../platform/permisos'
import { formatMesAnio, formatFechaHora } from '../../lib/fecha'

export default function DashboardPlataformaPage() {
  const navigate = useNavigate()
  const { data, isLoading, isError } = usePlatformMetrics()
  const { role } = usePlatformRole()

  // Actividad reciente: solo si el rol tiene acceso al módulo de auditoría.
  const verAuditoria = !!accesoModuloPlat(role, 'auditoria')
  const auditoria = usePlatformAuditoria({ page_size: 5 }, verAuditoria)
  const eventos = auditoria.data?.results ?? []

  // Alerta de vencimientos: solo roles con acceso al módulo de suscripciones.
  const verSuscripciones = !!accesoModuloPlat(role, 'suscripciones')
  const resumenSusc = useSuscripcionesResumen(verSuscripciones)
  const vencidas = resumenSusc.data
    ? resumenSusc.data.alertas.trial_vencido + resumenSusc.data.alertas.periodo_vencido
    : 0

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

      {/* Alerta de suscripciones vencidas (solo aviso; la suspensión es manual) */}
      {verSuscripciones && vencidas > 0 && (
        <div className="glass-card rounded-2xl px-5 py-4 flex flex-wrap items-center justify-between gap-3"
          style={{ border: '1px solid rgba(192,57,43,0.35)', background: 'rgba(192,57,43,0.07)' }}>
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0" style={{ background: 'rgba(192,57,43,0.12)' }}>
              <AlertTriangle className="w-5 h-5" style={{ color: '#C0392B' }} />
            </div>
            <p className="text-sm" style={{ color: '#8C2B21' }}>
              <strong>{vencidas} clínica{vencidas === 1 ? '' : 's'}</strong> con la prueba o el periodo vencido — la suspensión es manual.
            </p>
          </div>
          <button onClick={() => navigate('/plataforma/suscripciones')}
            className="inline-flex items-center gap-1 px-4 py-2 rounded-xl text-xs font-semibold text-white transition-all hover:brightness-110"
            style={{ background: '#C0392B' }}>
            Ver suscripciones <ChevronRight className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

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

          {/* Actividad reciente (auditoría) — solo roles con acceso al módulo */}
          {verAuditoria && (
            <div className="glass-card rounded-2xl overflow-hidden">
              <div className="flex items-center justify-between px-6 py-4 border-b border-white/50">
                <h2 className="text-base font-semibold text-gray-800">Actividad reciente</h2>
                <button onClick={() => navigate('/plataforma/auditoria')}
                  className="inline-flex items-center gap-1 text-xs font-semibold transition-colors hover:opacity-80"
                  style={{ color: '#B8860B' }}>
                  Ver auditoría <ChevronRight className="w-3.5 h-3.5" />
                </button>
              </div>
              {auditoria.isLoading ? (
                <div className="flex items-center justify-center gap-2 px-6 py-8 text-amber-700 text-sm">
                  <Loader2 className="w-4 h-4 animate-spin" /> Cargando actividad…
                </div>
              ) : auditoria.isError ? (
                <p className="px-6 py-8 text-center text-sm text-gray-400">No se pudo cargar la actividad reciente.</p>
              ) : eventos.length === 0 ? (
                <p className="px-6 py-8 text-center text-sm text-gray-400">Aún no hay actividad registrada.</p>
              ) : (
                eventos.map(ev => (
                  <div key={ev.id} className="flex items-center justify-between gap-3 px-6 py-3 border-b border-white/30">
                    <div className="flex items-center gap-3 min-w-0">
                      <div className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0" style={{ background: 'rgba(201,162,39,0.14)' }}>
                        <ScrollText className="w-4 h-4" style={{ color: '#C9A227' }} />
                      </div>
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-gray-800 truncate">{ev.description}</p>
                        <p className="text-xs text-gray-400 truncate">
                          {ev.actor_email ?? 'Sistema'}
                          {ev.tenant_name ? ` · ${ev.tenant_name}` : ''}
                        </p>
                      </div>
                    </div>
                    <div className="text-right shrink-0">
                      <span className="inline-block text-[11px] font-semibold px-2.5 py-1 rounded-full whitespace-nowrap"
                        style={{ background: 'rgba(201,162,39,0.16)', color: '#B8860B' }}>
                        {ev.action_display || ev.action}
                      </span>
                      <p className="text-[11px] text-gray-400 mt-1">{formatFechaHora(ev.created_at)}</p>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </>
      )}
    </PlatformLayout>
  )
}
