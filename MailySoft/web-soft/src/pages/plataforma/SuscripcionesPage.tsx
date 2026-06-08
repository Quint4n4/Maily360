import { Check } from 'lucide-react'
import PlatformLayout from '../../platform/PlatformLayout'
import { CLINICAS, ESTADO_CLINICA, mxn } from '../../data/clinicas'

const PLANES = [
  { nombre: 'Básico',  precio: 1500, destacado: false, features: ['1 consultorio', 'Hasta 3 usuarios', 'Agenda y pacientes', 'Recordatorios WhatsApp'] },
  { nombre: 'Pro',     precio: 4500, destacado: true,  features: ['Hasta 5 consultorios', 'Usuarios ilimitados', 'Expedientes completos', 'Finanzas y reportes'] },
  { nombre: 'Premium', precio: 8900, destacado: false, features: ['Consultorios ilimitados', 'Multi-sucursal', 'Soporte prioritario', 'Integraciones a medida'] },
]

const cuenta = (plan: string) => CLINICAS.filter(c => c.plan === plan).length

export default function SuscripcionesPage() {
  return (
    <PlatformLayout active="suscripciones">
      <div className="glass-card rounded-2xl px-6 py-5">
        <h1 className="text-2xl font-bold text-gray-900">Suscripciones</h1>
        <p className="text-sm text-gray-500">Planes y clínicas suscritas</p>
      </div>

      {/* Planes */}
      <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))' }}>
        {PLANES.map(p => (
          <div key={p.nombre} className="glass-card rounded-2xl p-6 relative"
            style={p.destacado ? { border: '2px solid #C9A227' } : {}}>
            {p.destacado && (
              <span className="absolute top-4 right-4 text-[10px] font-semibold uppercase px-2 py-0.5 rounded-full"
                style={{ background: '#C9A227', color: '#fff' }}>Popular</span>
            )}
            <h3 className="text-lg font-bold text-gray-900">{p.nombre}</h3>
            <p className="mt-1"><span className="text-2xl font-bold" style={{ color: '#B8860B' }}>{mxn(p.precio)}</span><span className="text-sm text-gray-400">/mes</span></p>
            <p className="text-xs text-gray-400 mt-1 mb-4">{cuenta(p.nombre)} clínicas en este plan</p>
            <ul className="space-y-2">
              {p.features.map(f => (
                <li key={f} className="flex items-center gap-2 text-sm text-gray-600">
                  <Check className="w-4 h-4 shrink-0" style={{ color: '#2E7D5B' }} /> {f}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      {/* Tabla de suscripciones */}
      <div className="glass-card rounded-2xl overflow-hidden">
        <div className="px-6 py-4 border-b border-white/50">
          <h2 className="text-base font-semibold text-gray-800">Clínicas suscritas</h2>
        </div>
        <div className="grid items-center px-6 py-3 text-xs font-semibold text-gray-500 border-b border-white/40"
          style={{ gridTemplateColumns: '2fr 1fr 1fr 1fr' }}>
          <span>Clínica</span><span>Plan</span><span>Estado</span><span>Ingreso/mes</span>
        </div>
        {CLINICAS.map(c => (
          <div key={c.id} className="grid items-center px-6 py-3 border-b border-white/30"
            style={{ gridTemplateColumns: '2fr 1fr 1fr 1fr' }}>
            <span className="text-sm font-medium text-gray-800">{c.nombre}</span>
            <span className="text-sm text-gray-600">{c.plan}</span>
            <span><span className={`badge ${ESTADO_CLINICA[c.estado].badge}`}>{ESTADO_CLINICA[c.estado].label}</span></span>
            <span className="text-sm font-semibold text-gray-800">{c.ingresoMensual ? mxn(c.ingresoMensual) : '—'}</span>
          </div>
        ))}
      </div>
    </PlatformLayout>
  )
}
