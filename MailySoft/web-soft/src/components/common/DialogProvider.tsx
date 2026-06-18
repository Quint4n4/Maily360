import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { AlertCircle, AlertTriangle, CheckCircle2, Info, X } from 'lucide-react'

/* ──────────────────────────────────────────────────────────────────────────
   DialogProvider — reemplaza window.confirm / window.alert por modales propios
   coherentes con el tema gold+white glass. Se renderiza con createPortal sobre
   document.body para que el backdrop-filter de las tarjetas glass no recorte el
   `fixed` (mismo patrón que PlantillaModal).

   Expone dos hooks promesa-based:
     const confirmar = useConfirm()
     if (await confirmar({ titulo, mensaje, peligro })) { ... }

     const aviso = useAviso()
     await aviso({ mensaje, tipo: 'error' })
   ────────────────────────────────────────────────────────────────────────── */

export interface ConfirmOptions {
  /** Título del diálogo. Por defecto "Confirmar". */
  titulo?: string
  /** Mensaje / pregunta a mostrar. */
  mensaje: ReactNode
  /** Texto del botón de confirmación. Por defecto "Confirmar". */
  textoConfirmar?: string
  /** Texto del botón de cancelación. Por defecto "Cancelar". */
  textoCancelar?: string
  /** Acción destructiva: pinta el botón de confirmar en rojo. */
  peligro?: boolean
}

export type AvisoTipo = 'info' | 'exito' | 'error'

export interface AvisoOptions {
  /** Título del aviso. Por defecto depende del tipo. */
  titulo?: string
  /** Mensaje a mostrar. */
  mensaje: ReactNode
  /** Tipo visual del aviso. Por defecto "info". */
  tipo?: AvisoTipo
  /** Texto del botón de cierre. Por defecto "Aceptar". */
  textoAceptar?: string
}

type ConfirmFn = (opts: ConfirmOptions) => Promise<boolean>
type AvisoFn = (opts: AvisoOptions) => Promise<void>

interface DialogContextValue {
  confirmar: ConfirmFn
  aviso: AvisoFn
}

const DialogContext = createContext<DialogContextValue | null>(null)

/* ── Estado interno de cada diálogo activo ───────────────────────────────── */
interface ConfirmState extends ConfirmOptions {
  id: number
  resolve: (v: boolean) => void
}
interface AvisoState extends AvisoOptions {
  id: number
  resolve: () => void
}

const OVERLAY_STYLE = { background: 'rgba(40,28,8,0.4)', backdropFilter: 'blur(6px)' } as const
const CARD_STYLE = {
  background: 'rgba(255,255,255,0.92)',
  backdropFilter: 'blur(30px) saturate(160%)',
} as const

const AVISO_META: Record<AvisoTipo, { titulo: string; Icon: typeof Info; color: string; bg: string }> = {
  info: { titulo: 'Aviso', Icon: Info, color: '#C9A227', bg: 'rgba(201,162,39,0.12)' },
  exito: { titulo: 'Listo', Icon: CheckCircle2, color: '#0d9488', bg: 'rgba(13,148,136,0.12)' },
  error: { titulo: 'Error', Icon: AlertCircle, color: '#dc2626', bg: 'rgba(220,38,38,0.10)' },
}

export function DialogProvider({ children }: { children: ReactNode }) {
  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null)
  const [avisoState, setAvisoState] = useState<AvisoState | null>(null)
  const idRef = useRef(0)

  const confirmar = useCallback<ConfirmFn>((opts) => {
    return new Promise<boolean>((resolve) => {
      idRef.current += 1
      setConfirmState({ ...opts, id: idRef.current, resolve })
    })
  }, [])

  const aviso = useCallback<AvisoFn>((opts) => {
    return new Promise<void>((resolve) => {
      idRef.current += 1
      setAvisoState({ ...opts, id: idRef.current, resolve })
    })
  }, [])

  const cerrarConfirm = useCallback((valor: boolean) => {
    setConfirmState((prev) => {
      prev?.resolve(valor)
      return null
    })
  }, [])

  const cerrarAviso = useCallback(() => {
    setAvisoState((prev) => {
      prev?.resolve()
      return null
    })
  }, [])

  const value = useMemo<DialogContextValue>(() => ({ confirmar, aviso }), [confirmar, aviso])

  return (
    <DialogContext.Provider value={value}>
      {children}
      {createPortal(
        <>
          <ConfirmDialog state={confirmState} onClose={cerrarConfirm} />
          <AvisoDialog state={avisoState} onClose={cerrarAviso} />
        </>,
        document.body,
      )}
    </DialogContext.Provider>
  )
}

/* ── Diálogo de confirmación (reemplazo de window.confirm) ────────────────── */
function ConfirmDialog({
  state,
  onClose,
}: {
  state: ConfirmState | null
  onClose: (valor: boolean) => void
}) {
  const peligro = state?.peligro ?? false
  return (
    <AnimatePresence>
      {state && (
        <motion.div
          key={state.id}
          className="fixed inset-0 z-[60] flex items-center justify-center px-4 py-10 overflow-y-auto"
          style={OVERLAY_STYLE}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={() => onClose(false)}
        >
          <motion.div
            role="alertdialog"
            aria-modal="true"
            className="relative w-full max-w-md rounded-3xl overflow-hidden shadow-2xl"
            style={CARD_STYLE}
            initial={{ y: 24, opacity: 0, scale: 0.98 }}
            animate={{ y: 0, opacity: 1, scale: 1 }}
            exit={{ y: 24, opacity: 0, scale: 0.98 }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start gap-4 px-6 pt-6">
              <div
                className="shrink-0 grid place-items-center w-11 h-11 rounded-2xl"
                style={{
                  color: peligro ? '#dc2626' : '#C9A227',
                  background: peligro ? 'rgba(220,38,38,0.10)' : 'rgba(201,162,39,0.12)',
                }}
              >
                {peligro ? <AlertTriangle className="w-6 h-6" /> : <AlertCircle className="w-6 h-6" />}
              </div>
              <div className="flex-1 min-w-0">
                <h3 className="text-lg font-semibold text-gray-800">{state.titulo ?? 'Confirmar'}</h3>
                <div className="mt-1 text-sm text-gray-600 whitespace-pre-line">{state.mensaje}</div>
              </div>
              <button
                onClick={() => onClose(false)}
                className="p-1.5 -mt-1 -mr-1 rounded-lg hover:bg-black/5 shrink-0"
                aria-label="Cerrar"
              >
                <X className="w-5 h-5 text-gray-400" />
              </button>
            </div>

            <div className="flex justify-end gap-2 px-6 py-5 mt-2">
              <button className="btn-secondary" onClick={() => onClose(false)}>
                {state.textoCancelar ?? 'Cancelar'}
              </button>
              <button
                className={peligro ? 'btn-danger' : 'btn-primary'}
                onClick={() => onClose(true)}
                autoFocus
              >
                {state.textoConfirmar ?? 'Confirmar'}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

/* ── Diálogo de aviso (reemplazo de window.alert) ─────────────────────────── */
function AvisoDialog({
  state,
  onClose,
}: {
  state: AvisoState | null
  onClose: () => void
}) {
  const meta = AVISO_META[state?.tipo ?? 'info']
  const Icon = meta.Icon
  return (
    <AnimatePresence>
      {state && (
        <motion.div
          key={state.id}
          className="fixed inset-0 z-[60] flex items-center justify-center px-4 py-10 overflow-y-auto"
          style={OVERLAY_STYLE}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            role="alertdialog"
            aria-modal="true"
            className="relative w-full max-w-md rounded-3xl overflow-hidden shadow-2xl"
            style={CARD_STYLE}
            initial={{ y: 24, opacity: 0, scale: 0.98 }}
            animate={{ y: 0, opacity: 1, scale: 1 }}
            exit={{ y: 24, opacity: 0, scale: 0.98 }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start gap-4 px-6 pt-6">
              <div
                className="shrink-0 grid place-items-center w-11 h-11 rounded-2xl"
                style={{ color: meta.color, background: meta.bg }}
              >
                <Icon className="w-6 h-6" />
              </div>
              <div className="flex-1 min-w-0">
                <h3 className="text-lg font-semibold text-gray-800">{state.titulo ?? meta.titulo}</h3>
                <div className="mt-1 text-sm text-gray-600 whitespace-pre-line break-words">{state.mensaje}</div>
              </div>
              <button
                onClick={onClose}
                className="p-1.5 -mt-1 -mr-1 rounded-lg hover:bg-black/5 shrink-0"
                aria-label="Cerrar"
              >
                <X className="w-5 h-5 text-gray-400" />
              </button>
            </div>

            <div className="flex justify-end px-6 py-5 mt-2">
              <button className="btn-primary" onClick={onClose} autoFocus>
                {state.textoAceptar ?? 'Aceptar'}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

/* ── Hooks públicos ───────────────────────────────────────────────────────── */
function useDialogContext(): DialogContextValue {
  const ctx = useContext(DialogContext)
  if (!ctx) throw new Error('useConfirm/useAviso deben usarse dentro de <DialogProvider>')
  return ctx
}

/** Hook promesa-based para confirmar acciones: `if (await confirmar({...})) {…}`. */
export function useConfirm(): ConfirmFn {
  return useDialogContext().confirmar
}

/** Hook promesa-based para mostrar avisos: `await aviso({ mensaje, tipo })`. */
export function useAviso(): AvisoFn {
  return useDialogContext().aviso
}
