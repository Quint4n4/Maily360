import { ScrollText, Lock } from 'lucide-react'

import Topbar from '../components/Topbar'
import CotizacionesTab from '../components/finanzas/CotizacionesTab'
import { can } from '../auth/permisos'
import { ALL_ROLES, useRole } from '../auth/useRole'

/**
 * Página top-level "Cotizaciones".
 *
 * El acceso al módulo lo decide el router (Guard con accesoModulo). Aquí, además,
 * gateamos la CREACIÓN con can(role, 'createQuote') — SOLO UX: el backend es la
 * autoridad. El selector de rol es la misma ayuda de demo que usa FinanzasPage
 * para validar la matriz de permisos hasta que la sesión real cablee el rol.
 */
export default function CotizacionesPage() {
  const { role, setRole } = useRole()
  const puedeVer = can(role, 'viewModule') || can(role, 'createQuote')

  return (
    <div className="min-h-screen" style={{ background: 'linear-gradient(135deg, #f6f1e4 0%, #faf7ef 100%)' }}>
      <Topbar active="cotizaciones" />

      <main className="max-w-4xl mx-auto px-4 md:px-6 py-6 space-y-5">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2" style={{ color: '#2A241B' }}>
              <ScrollText className="w-6 h-6" style={{ color: '#C9A227' }} />
              Cotizaciones
            </h1>
            <p className="text-sm" style={{ color: '#7A756C' }}>
              Cotiza servicios desde tu catálogo, descarga el PDF y márcalas como enviadas o aceptadas.
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

        {!puedeVer ? (
          <div className="glass-card rounded-2xl p-10 text-center">
            <Lock className="w-8 h-8 mx-auto mb-3" style={{ color: '#9A958C' }} />
            <p className="text-sm" style={{ color: '#7A756C' }}>
              Tu rol (<strong>{role}</strong>) no tiene acceso al módulo de cotizaciones.
            </p>
          </div>
        ) : (
          <CotizacionesTab role={role} />
        )}
      </main>
    </div>
  )
}
