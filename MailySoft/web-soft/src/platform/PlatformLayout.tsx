import { ReactNode } from 'react'
import PlatformTopbar from './PlatformTopbar'
import { PlatModulo } from './permisos'

export default function PlatformLayout({ active, children }: { active: PlatModulo; children: ReactNode }) {
  return (
    <div className="min-h-screen relative">
      <div className="fixed inset-0 -z-10" style={{ background: 'linear-gradient(135deg, #b89a52 0%, #d8c690 45%, #f1e8cf 100%)' }} />
      <div className="fixed inset-0 -z-10 bg-cover bg-center" style={{ backgroundImage: "url('/fondo-agenda.jpg')" }} />
      <div className="fixed inset-0 -z-10" style={{ background: 'rgba(255,255,255,0.22)' }} />

      <PlatformTopbar active={active} />

      <div className="p-3 sm:p-5 max-w-[1300px] mx-auto space-y-4 sm:space-y-5">
        {children}
      </div>
    </div>
  )
}
