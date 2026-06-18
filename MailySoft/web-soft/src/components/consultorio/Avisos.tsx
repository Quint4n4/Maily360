import { AlertCircle, CheckCircle2, Info, Lock } from 'lucide-react'

/** Alerta de errores (lista de mensajes de DRF). No se muestra si vacía. */
export function AlertaErrores({ errores }: { errores: string[] }) {
  if (errores.length === 0) return null
  return (
    <div className="flex items-start gap-2.5 rounded-xl px-3.5 py-3 bg-red-50 border border-red-200 text-sm text-red-700">
      <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
      <ul className="space-y-0.5">
        {errores.map((e, i) => (
          <li key={i}>{e}</li>
        ))}
      </ul>
    </div>
  )
}

/** Aviso breve de éxito (se muestra solo si `visible`). */
export function AvisoGuardado({ visible }: { visible: boolean }) {
  if (!visible) return null
  return (
    <div className="flex items-center gap-2 rounded-xl px-3.5 py-2.5 bg-emerald-50 border border-emerald-200 text-sm text-emerald-700">
      <CheckCircle2 className="w-4 h-4 shrink-0" /> Cambios guardados.
    </div>
  )
}

/** Banner de "solo lectura": el usuario puede ver pero no editar esta sección. */
export function AvisoSoloLectura({ texto }: { texto?: string }) {
  return (
    <div className="flex items-center gap-2 rounded-xl px-3.5 py-2.5 bg-amber-50 border border-amber-200 text-sm text-amber-800">
      <Lock className="w-4 h-4 shrink-0" />
      {texto ?? 'Tienes acceso de solo lectura en esta sección.'}
    </div>
  )
}

/** Estado vacío / informativo genérico. */
export function AvisoInfo({ texto }: { texto: string }) {
  return (
    <div className="flex items-start gap-2.5 rounded-xl px-3.5 py-3 bg-blue-50 border border-blue-200 text-sm text-blue-700">
      <Info className="w-4 h-4 mt-0.5 shrink-0" />
      <span>{texto}</span>
    </div>
  )
}

/** Nota auxiliar discreta (texto gris pequeño). */
export function Nota({ children }: { children: React.ReactNode }) {
  return <p className="text-xs text-gray-500 leading-relaxed">{children}</p>
}
