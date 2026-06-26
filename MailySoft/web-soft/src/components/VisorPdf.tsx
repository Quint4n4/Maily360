/**
 * VisorPdf — visor inline de PDF en un modal.
 *
 * Reutilizable en TODOS los lugares que generan un PDF (reportes, cotizaciones,
 * recetas, libro clínico, estado de cuenta). En vez de descargar el archivo a
 * ciegas, el usuario lo VE embebido (<iframe>) y, si quiere, lo descarga con el
 * botón del encabezado.
 *
 * Contrato: el caller pasa `cargar()`, que devuelve el Blob del PDF. Esa función
 * debe pasar SIEMPRE por el cliente HTTP central (requestBlob) — el visor solo
 * consume el Blob y nunca toca `fetch` ni tokens.
 *
 * Estados: cargando (spinner), error (incluye 403 vía ApiError → mensaje claro),
 * y listo (iframe). El object URL temporal se revoca al desmontar/cerrar para no
 * fugar memoria.
 */

import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Download, Loader2, AlertCircle } from 'lucide-react'

import { ApiError } from '../lib/http'

interface VisorPdfProps {
  /** Título mostrado en el encabezado del modal. */
  titulo: string
  /** Nombre con el que se descarga el archivo (incluye .pdf). */
  nombreArchivo: string
  /** Obtiene el Blob del PDF (debe ir por el cliente HTTP central). */
  cargar: () => Promise<Blob>
  /** Cierra el visor. */
  onClose: () => void
}

type Estado =
  | { fase: 'cargando' }
  | { fase: 'listo'; url: string }
  | { fase: 'error'; mensaje: string }

/** Traduce el error de `cargar()` a un mensaje claro (403 incluido vía ApiError). */
function mensajeDeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 403) return 'No tienes permiso para ver este documento.'
    if (err.isNetwork) return 'No se pudo conectar con el servidor. Revisa tu conexión.'
    return err.message || `No se pudo generar el PDF (error ${err.status}).`
  }
  if (err instanceof Error && err.message) return err.message
  return 'No se pudo generar el PDF.'
}

export default function VisorPdf({ titulo, nombreArchivo, cargar, onClose }: VisorPdfProps) {
  const [estado, setEstado] = useState<Estado>({ fase: 'cargando' })
  // Object URL vivo: se conserva en un ref para revocarlo al desmontar sin
  // depender del estado (evita revocar uno nuevo por una limpieza tardía).
  const urlRef = useRef<string | null>(null)

  useEffect(() => {
    let activo = true

    void (async () => {
      try {
        const blob = await cargar()
        if (!activo) return
        const url = URL.createObjectURL(blob)
        urlRef.current = url
        setEstado({ fase: 'listo', url })
      } catch (err) {
        if (!activo) return
        setEstado({ fase: 'error', mensaje: mensajeDeError(err) })
      }
    })()

    return () => {
      activo = false
      if (urlRef.current) {
        URL.revokeObjectURL(urlRef.current)
        urlRef.current = null
      }
    }
    // `cargar` se pasa como closure estable por uso (no se recrea por render
    // relevante); el efecto debe correr una sola vez al montar el visor.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /** Descarga el PDF ya cargado usando el object URL vivo (sin volver a pedirlo). */
  const descargar = (): void => {
    if (estado.fase !== 'listo') return
    const a = document.createElement('a')
    a.href = estado.url
    a.download = nombreArchivo
    document.body.appendChild(a)
    a.click()
    a.remove()
  }

  return createPortal(
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 z-[100] flex items-center justify-center p-4 md:p-8"
        style={{ background: 'rgba(40,28,8,0.4)', backdropFilter: 'blur(6px)' }}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
        role="dialog"
        aria-modal="true"
      >
        <motion.div
          className="relative w-full max-w-4xl rounded-3xl overflow-hidden bg-white shadow-2xl flex flex-col"
          style={{ maxHeight: '92vh' }}
          initial={{ opacity: 0, y: 24, scale: 0.97 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 24, scale: 0.97 }}
          transition={{ duration: 0.28, ease: [0.25, 0.46, 0.45, 0.94] }}
          onClick={(e) => e.stopPropagation()}
        >
          {/* ── Encabezado ── */}
          <div className="px-6 py-4 flex items-center gap-3 border-b border-gray-100 shrink-0">
            <h2 className="flex-1 min-w-0 text-base font-bold text-gray-900 truncate">{titulo}</h2>
            <button
              type="button"
              onClick={descargar}
              disabled={estado.fase !== 'listo'}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-50 shrink-0"
              style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
              title="Descargar PDF"
            >
              <Download className="w-4 h-4" /> Descargar
            </button>
            <button
              type="button"
              onClick={onClose}
              className="text-gray-400 hover:text-gray-700 transition-colors shrink-0"
              title="Cerrar"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* ── Cuerpo: spinner / error / iframe ── */}
          <div className="flex-1 min-h-0" style={{ background: 'rgba(0,0,0,0.03)' }}>
            {estado.fase === 'cargando' && (
              <div
                className="w-full h-[80vh] flex flex-col items-center justify-center gap-3"
                style={{ color: '#9A958C' }}
              >
                <Loader2 className="w-7 h-7 animate-spin" />
                <p className="text-sm">Generando el PDF…</p>
              </div>
            )}

            {estado.fase === 'error' && (
              <div className="w-full h-[80vh] flex flex-col items-center justify-center gap-3 px-6 text-center">
                <AlertCircle className="w-8 h-8" style={{ color: '#C0392B' }} />
                <p className="text-sm font-medium" style={{ color: '#C0392B' }}>
                  {estado.mensaje}
                </p>
              </div>
            )}

            {estado.fase === 'listo' && (
              <iframe
                src={estado.url}
                title={titulo}
                className="w-full h-[80vh] border-0"
              />
            )}
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>,
    document.body,
  )
}
