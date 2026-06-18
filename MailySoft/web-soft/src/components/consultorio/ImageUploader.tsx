import { useRef } from 'react'
import { ImagePlus, Loader2, Trash2 } from 'lucide-react'

interface Props {
  /** URL de la imagen actual, o null. */
  src?: string | null
  /** Etiqueta accesible / texto del placeholder. */
  label: string
  /** Subiendo (muestra spinner y bloquea). */
  uploading?: boolean
  /** Se llama con el archivo elegido. */
  onFile: (file: File) => void
  /** Si se pasa, muestra un botón de quitar (no soportado por todos los campos). */
  onClear?: () => void
  /** Alto del recuadro en px (ancho = 100%). */
  height?: number
}

/**
 * Uploader rectangular para imágenes de la clínica (logo, membretes, sello,
 * foto del médico, logo de universidad). Acepta JPG/PNG/WEBP (igual que el
 * backend). Muestra la imagen actual o un placeholder con botón de subir.
 */
export default function ImageUploader({
  src,
  label,
  uploading = false,
  onFile,
  onClear,
  height = 140,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null)

  const pick = () => {
    if (!uploading) inputRef.current?.click()
  }
  const onChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) onFile(file)
    e.target.value = '' // permite re-elegir el mismo archivo
  }

  return (
    <div className="space-y-2">
      <div
        onClick={pick}
        className="group relative w-full rounded-2xl overflow-hidden flex items-center justify-center transition-all"
        style={{
          height,
          background: src ? 'rgba(255,255,255,0.6)' : 'rgba(201,162,39,0.08)',
          border: '1.5px dashed rgba(201,162,39,0.5)',
          cursor: uploading ? 'default' : 'pointer',
        }}
      >
        {src ? (
          <img src={src} alt={label} className="max-h-full max-w-full object-contain" />
        ) : (
          <div className="flex flex-col items-center gap-1.5" style={{ color: '#B8860B' }}>
            <ImagePlus className="w-7 h-7" />
            <span className="text-xs font-medium">{label}</span>
            <span className="text-[11px] text-gray-400">JPG, PNG o WEBP</span>
          </div>
        )}

        {src && !uploading && (
          <div
            className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
            style={{ background: 'rgba(40,28,8,0.4)' }}
          >
            <span className="flex items-center gap-1.5 text-white text-sm font-medium">
              <ImagePlus className="w-4 h-4" /> Cambiar
            </span>
          </div>
        )}

        {uploading && (
          <div
            className="absolute inset-0 flex items-center justify-center"
            style={{ background: 'rgba(40,28,8,0.5)' }}
          >
            <Loader2 className="w-6 h-6 text-white animate-spin" />
          </div>
        )}

        <input
          ref={inputRef}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          className="hidden"
          onChange={onChange}
        />
      </div>

      {src && onClear && !uploading && (
        <button
          type="button"
          onClick={onClear}
          className="inline-flex items-center gap-1.5 text-xs text-red-500 hover:text-red-600 transition-colors"
        >
          <Trash2 className="w-3.5 h-3.5" /> Quitar
        </button>
      )}
    </div>
  )
}
