import { Activity, Server, Database, Cpu, CheckCircle2, AlertTriangle } from 'lucide-react'
import PlatformLayout from '../../platform/PlatformLayout'

const METRICAS = [
  { icon: Activity, label: 'Disponibilidad (30 días)', valor: '99.98%', color: '#2E7D5B' },
  { icon: Server,   label: 'Latencia API (p95)',       valor: '128 ms', color: '#3A6EA5' },
  { icon: Database, label: 'Base de datos',            valor: 'OK',     color: '#2E7D5B' },
  { icon: Cpu,      label: 'Workers Celery',           valor: '4 / 4',  color: '#2E7D5B' },
]

const SERVICIOS = [
  { nombre: 'API (Django + DRF)', estado: 'Operativo', ok: true },
  { nombre: 'Base de datos (PostgreSQL)', estado: 'Operativo', ok: true },
  { nombre: 'Cache / broker (Redis)', estado: 'Operativo', ok: true },
  { nombre: 'Worker de recordatorios (Celery)', estado: 'Operativo', ok: true },
  { nombre: 'Envío WhatsApp', estado: 'Degradado', ok: false },
]

const INCIDENTES = [
  { fecha: '03 jun 2026 · 14:20', texto: 'Latencia elevada en envío de WhatsApp (resuelto).', ok: true },
  { fecha: '28 may 2026 · 09:05', texto: 'Reinicio programado de workers.', ok: true },
]

export default function SistemaPage() {
  return (
    <PlatformLayout active="sistema">
      <div className="glass-card rounded-2xl px-6 py-5">
        <h1 className="text-2xl font-bold text-gray-900">Salud del sistema</h1>
        <p className="text-sm text-gray-500">Estado de los servicios de la plataforma</p>
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

      <div className="grid gap-5 md:grid-cols-2">
        {/* Servicios */}
        <div className="glass-card rounded-2xl overflow-hidden">
          <div className="px-6 py-4 border-b border-white/50"><h2 className="text-base font-semibold text-gray-800">Servicios</h2></div>
          {SERVICIOS.map(s => (
            <div key={s.nombre} className="flex items-center justify-between px-6 py-3 border-b border-white/30">
              <span className="text-sm text-gray-800">{s.nombre}</span>
              <span className="flex items-center gap-1.5 text-sm font-medium" style={{ color: s.ok ? '#2E7D5B' : '#C0392B' }}>
                {s.ok ? <CheckCircle2 className="w-4 h-4" /> : <AlertTriangle className="w-4 h-4" />}
                {s.estado}
              </span>
            </div>
          ))}
        </div>

        {/* Incidentes */}
        <div className="glass-card rounded-2xl overflow-hidden">
          <div className="px-6 py-4 border-b border-white/50"><h2 className="text-base font-semibold text-gray-800">Incidentes recientes</h2></div>
          {INCIDENTES.map((it, i) => (
            <div key={i} className="flex items-start gap-3 px-6 py-3 border-b border-white/30">
              <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" style={{ color: '#2E7D5B' }} />
              <div>
                <p className="text-sm text-gray-800">{it.texto}</p>
                <p className="text-xs text-gray-400">{it.fecha}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </PlatformLayout>
  )
}
