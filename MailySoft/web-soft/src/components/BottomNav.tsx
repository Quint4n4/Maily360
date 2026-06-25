import { useEffect } from 'react'
import type { ComponentType } from 'react'

export interface BottomNavItem {
  key: string
  label: string
  Icon: ComponentType<{ className?: string }>
  active: boolean
  onClick: () => void
}

/**
 * Barra de navegación inferior estilo app, visible solo en móvil (<md).
 * En escritorio la navegación vive en la Topbar (que oculta su nav en móvil).
 * Mientras está montada añade la clase `.has-bottom-nav` al body para reservar
 * espacio al pie y no tapar el contenido (ver index.css).
 */
export default function BottomNav({ items }: { items: BottomNavItem[] }) {
  useEffect(() => {
    document.body.classList.add('has-bottom-nav')
    return () => document.body.classList.remove('has-bottom-nav')
  }, [])

  return (
    <nav
      className="bottom-nav md:hidden fixed bottom-0 inset-x-0 z-40 flex items-stretch justify-around"
      style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
    >
      {items.map(({ key, label, Icon, active, onClick }) => (
        <button
          key={key}
          onClick={onClick}
          aria-label={label}
          aria-current={active ? 'page' : undefined}
          className="flex flex-col items-center justify-center gap-0.5 flex-1 min-w-0 py-2 transition-colors"
          style={{ color: active ? '#C9A227' : '#7A756C' }}
        >
          <Icon className="w-[22px] h-[22px]" />
          <span className="text-[10px] font-medium leading-none truncate max-w-full px-0.5">{label}</span>
        </button>
      ))}
    </nav>
  )
}
