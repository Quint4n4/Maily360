import { ScrollText, Lock } from 'lucide-react'

import Topbar from '../components/Topbar'
import CotizacionesTab from '../components/finanzas/CotizacionesTab'
import { can } from '../auth/permisos'
import { useRole } from '../auth/RoleContext'

/**
 * Página top-level "Cotizaciones".
 *
 * El acceso al módulo lo decide el router (Guard con accesoModulo). Aquí, además,
 * gateamos la CREACIÓN con can(role, 'createQuote') — SOLO UX: el backend es la
 * autoridad. El rol viene de la sesión real (/me/ → active_role) vía RoleContext.
 */
export default function CotizacionesPage() {
  const { role } = useRole()
  const puedeVer = can(role, 'viewModule') || can(role, 'createQuote')

  return (
    <div className="min-h-screen relative">
      <div className="fixed inset-0 -z-10" style={{ background: 'linear-gradient(135deg, #b89a52 0%, #d8c690 45%, #f1e8cf 100%)' }} />
      <div className="fixed inset-0 -z-10 bg-cover bg-center" style={{ backgroundImage: "url('/fondo-agenda.jpg')" }} />
      <div className="fixed inset-0 -z-10" style={{ background: 'rgba(255,255,255,0.20)' }} />
      <Topbar active="cotizaciones" />

      <main className="max-w-4xl mx-auto px-4 md:px-6 py-6 space-y-5">
        <div className="glass-card rounded-2xl px-6 py-5 flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2" style={{ color: '#2A241B' }}>
              <ScrollText className="w-6 h-6" style={{ color: '#C9A227' }} />
              Cotizaciones
            </h1>
            <p className="text-sm" style={{ color: '#7A756C' }}>
              Cotiza servicios desde tu catálogo, descarga el PDF y márcalas como enviadas o aceptadas.
            </p>
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
