import { useState } from 'react'
import { Loader2, Plus, Tag, X } from 'lucide-react'
import { useCategories, useCreateCategory, useDeleteCategory } from '../../hooks/clinica'
import { erroresDe } from '../../lib/apiErrors'
import type { PatientCategoryOut } from '../../types/clinica'
import { AlertaErrores, AvisoSoloLectura, Nota } from './Avisos'
import { useConfirm } from '../common/DialogProvider'

interface Props {
  editable: boolean
}

/** Sección 5: catálogo de categorías de paciente (chips). */
export default function SeccionCategorias({ editable }: Props) {
  const categoriasQ = useCategories()
  const crear = useCreateCategory()
  const borrar = useDeleteCategory()
  const confirmar = useConfirm()
  const [nombre, setNombre] = useState('')
  const [errores, setErrores] = useState<string[]>([])

  const categorias = categoriasQ.data?.results ?? []

  const agregar = async () => {
    setErrores([])
    const limpio = nombre.trim()
    if (!limpio) {
      setErrores(['Escribe un nombre para la categoría.'])
      return
    }
    try {
      await crear.mutateAsync({ name: limpio })
      setNombre('')
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  const onBorrar = async (cat: PatientCategoryOut) => {
    if (!(await confirmar({ titulo: 'Eliminar categoría', mensaje: `¿Eliminar la categoría “${cat.name}”?`, peligro: true, textoConfirmar: 'Eliminar' }))) return
    setErrores([])
    try {
      await borrar.mutateAsync(cat.id)
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  return (
    <div className="space-y-5">
      {!editable && <AvisoSoloLectura texto="Puedes ver las categorías, pero solo Dueño/Administrador las edita." />}
      <Nota>Las categorías te ayudan a clasificar pacientes (p. ej. “Premium”, “Pediátrico”).</Nota>
      <AlertaErrores errores={errores} />

      {editable && (
        <div className="flex items-center gap-2 max-w-md">
          <input
            className="input flex-1"
            placeholder="Nueva categoría"
            value={nombre}
            onChange={(e) => setNombre(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') void agregar() }}
          />
          <button className="btn-primary" onClick={agregar} disabled={crear.isPending}>
            {crear.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
            Agregar
          </button>
        </div>
      )}

      {categoriasQ.isLoading ? (
        <div className="flex items-center justify-center py-10 text-gray-400">
          <Loader2 className="w-5 h-5 animate-spin mr-2" /> Cargando categorías…
        </div>
      ) : categoriasQ.isError ? (
        <AlertaErrores errores={erroresDe(categoriasQ.error)} />
      ) : categorias.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-10 text-gray-400">
          <Tag className="w-8 h-8 mb-2 opacity-50" />
          <p className="text-sm">Aún no hay categorías.</p>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {categorias.map((cat) => (
            <span
              key={cat.id}
              className="inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-medium"
              style={{ background: 'rgba(201,162,39,0.14)', color: '#B8860B' }}
            >
              <Tag className="w-3.5 h-3.5" />
              {cat.name}
              {editable && (
                <button
                  onClick={() => onBorrar(cat)}
                  className="ml-0.5 rounded-full hover:bg-black/10 p-0.5 transition-colors"
                  aria-label={`Quitar ${cat.name}`}
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
