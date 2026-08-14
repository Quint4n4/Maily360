import { ReactNode } from 'react'
import PlatformTopbar from './PlatformTopbar'
import { PlatModulo } from './permisos'

export default function PlatformLayout({ active, children }: { active: PlatModulo; children: ReactNode }) {
  return (
    <div className="min-h-screen relative">
      {/* Fondo plano: la foto de seda dorada quedaba DEBAJO de los datos
          (tablas, tarjetas, la reja de la agenda) y les restaba legibilidad. */}
      <div className="fixed inset-0 -z-10 bg-fondo" />

      <PlatformTopbar active={active} />

      <div className="p-3 sm:p-5 max-w-[1300px] mx-auto space-y-4 sm:space-y-5">
        {children}
      </div>
    </div>
  )
}
