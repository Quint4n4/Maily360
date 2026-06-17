/**
 * Acordeon — lista de secciones colapsables (estilo expediente legacy).
 *
 * Varias secciones pueden estar abiertas a la vez (estado independiente por item).
 * Cada AcordeonItem renderiza su contenido SOLO cuando está abierto (lazy), para
 * no disparar las queries de todas las secciones de golpe.
 */

import { useState, type ReactNode } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronDown } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

export function Acordeon({ children }: { children: ReactNode }) {
  return <div className="space-y-3">{children}</div>
}

interface AcordeonItemProps {
  title: string
  icon: LucideIcon
  /** Si arranca expandida (p. ej. Enfermería). */
  defaultOpen?: boolean
  /** Contenido pesado: función para que solo se evalúe/monte al abrir (lazy). */
  children: () => ReactNode
}

export function AcordeonItem({ title, icon: Icon, defaultOpen = false, children }: AcordeonItemProps) {
  const [open, setOpen] = useState(defaultOpen)
  /** Una vez abierta, conservamos el contenido montado para no perder estado/refetch. */
  const [seenOpen, setSeenOpen] = useState(defaultOpen)

  const toggle = () => {
    setOpen(v => {
      const next = !v
      if (next) setSeenOpen(true)
      return next
    })
  }

  return (
    <div
      className="rounded-2xl overflow-hidden"
      style={{
        background: 'rgba(255,255,255,0.72)',
        backdropFilter: 'blur(14px)',
        border: '1px solid rgba(255,255,255,0.7)',
        boxShadow: '0 6px 20px rgba(60,42,12,0.10)',
      }}
    >
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className="w-full flex items-center justify-between gap-3 px-5 py-4 text-left transition-colors hover:bg-white/40"
      >
        <span className="flex items-center gap-2.5">
          <Icon className="w-5 h-5 shrink-0" style={{ color: '#C9A227' }} />
          <span className="text-sm font-semibold text-gray-900">{title}</span>
        </span>
        <motion.span
          animate={{ rotate: open ? 180 : 0 }}
          transition={{ duration: 0.25, ease: 'easeInOut' }}
          className="shrink-0"
        >
          <ChevronDown className="w-5 h-5" style={{ color: '#9A7B1E' }} />
        </motion.span>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="content"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.28, ease: [0.25, 0.46, 0.45, 0.94] }}
            className="overflow-hidden"
          >
            <div className="px-5 pb-5 pt-1 border-t border-amber-900/10">
              {/* Lazy: el contenido solo se evalúa cuando la sección ya se abrió. */}
              {seenOpen ? children() : null}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
