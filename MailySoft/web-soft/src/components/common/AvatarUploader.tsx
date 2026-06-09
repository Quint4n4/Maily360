import { useRef } from 'react'
import { Camera, Loader2 } from 'lucide-react'

interface Props {
  /** URL de la imagen, o null/undefined para mostrar iniciales. */
  src?: string | null
  /** Iniciales a mostrar cuando no hay imagen. */
  initials: string
  /** Diámetro en px. */
  size?: number
  /** Si true, al hacer click abre el selector de archivo. */
  editable?: boolean
  /** true mientras se sube (muestra spinner). */
  uploading?: boolean
  /** Se llama con el archivo seleccionado. */
  onFile?: (file: File) => void
}

/**
 * Avatar circular reutilizable. Muestra la foto si existe; si no, las iniciales.
 * Si `editable`, al pasar el cursor aparece un ícono de cámara y al hacer click
 * abre el selector de imagen.
 */
export default function AvatarUploader({ src, initials, size = 112, editable = false, uploading = false, onFile }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)

  const pick = () => {
    if (editable && !uploading) inputRef.current?.click()
  }
  const onChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file && onFile) onFile(file)
    e.target.value = '' // permite volver a elegir el mismo archivo
  }

  const fontSize = Math.round(size * 0.34)

  return (
    <div
      onClick={pick}
      className="group relative rounded-full overflow-hidden flex items-center justify-center font-bold shrink-0"
      style={{
        width: size, height: size, fontSize,
        background: 'rgba(201,162,39,0.18)', color: '#B8860B',
        border: '4px solid rgba(255,255,255,0.85)', boxShadow: '0 12px 36px rgba(60,42,12,0.25)',
        cursor: editable && !uploading ? 'pointer' : 'default',
      }}
    >
      {src
        ? <img src={src} alt="" className="w-full h-full object-cover" />
        : <span>{initials}</span>}

      {/* Overlay de cámara al pasar el cursor (solo editable) */}
      {editable && !uploading && (
        <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity" style={{ background: 'rgba(40,28,8,0.45)' }}>
          <Camera className="text-white" style={{ width: size * 0.28, height: size * 0.28 }} />
        </div>
      )}
      {/* Spinner mientras sube */}
      {uploading && (
        <div className="absolute inset-0 flex items-center justify-center" style={{ background: 'rgba(40,28,8,0.5)' }}>
          <Loader2 className="text-white animate-spin" style={{ width: size * 0.28, height: size * 0.28 }} />
        </div>
      )}

      {editable && (
        <input ref={inputRef} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={onChange} />
      )}
    </div>
  )
}
