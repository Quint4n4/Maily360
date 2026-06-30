/**
 * SeccionServicios — catálogo de servicios cobrables de la clínica (ServiceConcept
 * del módulo finanzas). El dueño/admin define aquí los conceptos con su precio base
 * y, opcionalmente, sus claves SAT para facturación CFDI.
 *
 * Permisos (UX; el backend es la autoridad vía FinanceConceptPermission):
 *   - Ver: roles de finanzas. Crear/editar/desactivar: solo owner/admin → si el
 *     usuario no puede, el backend devuelve 403 y la UI lo muestra sin romperse.
 *
 * Reúsa el patrón de las otras secciones de Mi Consultorio (ver SeccionCategorias /
 * SeccionHistoriaClinica): listado, alta, edición inline, estados de carga/vacío/error.
 */

import { useMemo, useState } from 'react'
import { ChevronDown, DollarSign, Loader2, Pencil, Plus, Power, Save, X } from 'lucide-react'
import {
  useConcepts,
  useCreateConcept,
  useDeactivateConcept,
  useUpdateConcept,
} from '../../hooks/finanzas'
import type { ConceptInput, ServiceConcept } from '../../api/finanzas'
import { erroresDe } from '../../lib/apiErrors'
import { formatMoney } from '../../lib/format'
import { AlertaErrores, AvisoSoloLectura, Nota } from './Avisos'
import { useConfirm } from '../common/DialogProvider'

interface Props {
  editable: boolean
}

/** Borrador del formulario (alta o edición). El precio se captura como texto. */
interface Borrador {
  name: string
  /** Precio base como texto del input; se convierte a número al enviar. */
  base_price: string
  sat_product_key: string
  sat_unit_key: string
}

const BORRADOR_VACIO: Borrador = {
  name: '', base_price: '', sat_product_key: '', sat_unit_key: '',
}

function borradorDe(c: ServiceConcept): Borrador {
  return {
    name: c.name,
    base_price: String(c.base_price),
    sat_product_key: c.sat_product_key,
    sat_unit_key: c.sat_unit_key,
  }
}

/** Valida el borrador en el front (UX) y lo convierte al payload de la API. */
function aPayload(b: Borrador): { input: ConceptInput } | { errores: string[] } {
  const errores: string[] = []
  const name = b.name.trim()
  if (!name) errores.push('Escribe el nombre del servicio.')
  const precio = Number(b.base_price)
  if (b.base_price.trim() === '' || !Number.isFinite(precio) || precio < 0) {
    errores.push('Escribe un precio válido (0 o mayor).')
  }
  if (errores.length) return { errores }
  return {
    input: {
      name,
      base_price: precio,
      sat_product_key: b.sat_product_key.trim(),
      sat_unit_key: b.sat_unit_key.trim(),
    },
  }
}

/** Sección "Servicios y precios": catálogo CRUD de conceptos cobrables. */
export default function SeccionServicios({ editable }: Props) {
  // Incluye inactivos para poder reactivarlos desde el panel de gestión.
  const serviciosQ = useConcepts({ includeInactive: true })
  const crear = useCreateConcept()
  const actualizar = useUpdateConcept()
  const desactivar = useDeactivateConcept()
  const confirmar = useConfirm()

  const [errores, setErrores] = useState<string[]>([])
  const [agregando, setAgregando] = useState(false)
  const [nuevo, setNuevo] = useState<Borrador>(BORRADOR_VACIO)
  const [editId, setEditId] = useState<string | null>(null)
  const [edicion, setEdicion] = useState<Borrador>(BORRADOR_VACIO)

  const servicios = useMemo(() => serviciosQ.data?.results ?? [], [serviciosQ.data])

  const onCrear = async () => {
    setErrores([])
    const r = aPayload(nuevo)
    if ('errores' in r) { setErrores(r.errores); return }
    try {
      await crear.mutateAsync(r.input)
      setNuevo(BORRADOR_VACIO)
      setAgregando(false)
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  const iniciarEdicion = (c: ServiceConcept) => {
    setErrores([])
    setEditId(c.id)
    setEdicion(borradorDe(c))
  }

  const onGuardarEdicion = async () => {
    if (!editId) return
    setErrores([])
    const r = aPayload(edicion)
    if ('errores' in r) { setErrores(r.errores); return }
    try {
      await actualizar.mutateAsync({ id: editId, input: r.input })
      setEditId(null)
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  const onDesactivar = async (c: ServiceConcept) => {
    if (!(await confirmar({
      titulo: 'Desactivar servicio',
      mensaje: `¿Desactivar “${c.name}”? Ya no aparecerá al crear cobros o cotizaciones, pero los registros existentes se conservan.`,
      peligro: true,
      textoConfirmar: 'Desactivar',
    }))) return
    setErrores([])
    try {
      await desactivar.mutateAsync(c.id)
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  const onReactivar = async (c: ServiceConcept) => {
    setErrores([])
    try {
      await actualizar.mutateAsync({ id: c.id, input: { is_active: true } })
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  return (
    <div className="space-y-5">
      {!editable && <AvisoSoloLectura texto="Puedes ver los servicios, pero solo Dueño/Administrador los edita." />}
      <Nota>
        Define aquí los servicios cobrables de tu clínica (p. ej. “Consulta general”, “Limpieza dental”)
        con su precio base. Estos conceptos se usan al crear cobros y cotizaciones. Las claves SAT son
        opcionales y solo se necesitan para facturar (CFDI).
      </Nota>

      <AlertaErrores errores={errores} />

      {editable && !agregando && (
        <button className="btn-primary" onClick={() => { setAgregando(true); setErrores([]) }}>
          <Plus className="w-4 h-4" /> Agregar servicio
        </button>
      )}

      {/* Formulario de alta */}
      {editable && agregando && (
        <EditorServicio
          borrador={nuevo}
          setBorrador={setNuevo}
          guardando={crear.isPending}
          onGuardar={onCrear}
          onCancelar={() => { setAgregando(false); setNuevo(BORRADOR_VACIO); setErrores([]) }}
          textoGuardar="Crear servicio"
        />
      )}

      {/* Listado */}
      {serviciosQ.isLoading ? (
        <div className="flex items-center justify-center py-10 text-gray-400">
          <Loader2 className="w-5 h-5 animate-spin mr-2" /> Cargando servicios…
        </div>
      ) : serviciosQ.isError ? (
        <AlertaErrores errores={erroresDe(serviciosQ.error)} />
      ) : servicios.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-10 text-gray-400">
          <DollarSign className="w-8 h-8 mb-2 opacity-50" />
          <p className="text-sm">Aún no has agregado servicios.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {servicios.map((c) =>
            editId === c.id ? (
              <EditorServicio
                key={c.id}
                borrador={edicion}
                setBorrador={setEdicion}
                guardando={actualizar.isPending}
                onGuardar={onGuardarEdicion}
                onCancelar={() => { setEditId(null); setErrores([]) }}
                textoGuardar="Guardar cambios"
              />
            ) : (
              <FilaServicio
                key={c.id}
                servicio={c}
                editable={editable}
                onEditar={() => iniciarEdicion(c)}
                onDesactivar={() => onDesactivar(c)}
                onReactivar={() => onReactivar(c)}
                ocupado={desactivar.isPending || actualizar.isPending}
              />
            ),
          )}
        </div>
      )}
    </div>
  )
}

// ── Fila de un servicio (modo lectura) ───────────────────────────────────────

function FilaServicio({
  servicio, editable, onEditar, onDesactivar, onReactivar, ocupado,
}: {
  servicio: ServiceConcept
  editable: boolean
  onEditar: () => void
  onDesactivar: () => void
  onReactivar: () => void
  ocupado: boolean
}) {
  return (
    <div
      className="flex items-center gap-3 rounded-xl px-3.5 py-2.5"
      style={{
        background: servicio.is_active ? 'rgba(255,255,255,0.72)' : 'rgba(245,245,244,0.7)',
        border: '1px solid rgba(201,162,39,0.18)',
        opacity: servicio.is_active ? 1 : 0.7,
      }}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium text-gray-800">{servicio.name}</span>
          {!servicio.is_active && <span className="badge badge-warning">Inactivo</span>}
        </div>
        {(servicio.sat_product_key || servicio.sat_unit_key) && (
          <div className="flex items-center gap-2 mt-0.5 text-[11px] text-gray-400">
            {servicio.sat_product_key && <span>Clave SAT {servicio.sat_product_key}</span>}
            {servicio.sat_unit_key && <span>· Unidad {servicio.sat_unit_key}</span>}
          </div>
        )}
      </div>
      <span className="text-sm font-semibold shrink-0" style={{ color: '#B8860B' }}>
        {formatMoney(servicio.base_price)}
      </span>
      {editable && (
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={onEditar}
            className="p-1.5 rounded-lg text-amber-700 hover:bg-amber-50 transition-colors"
            aria-label="Editar servicio"
          >
            <Pencil className="w-4 h-4" />
          </button>
          {servicio.is_active ? (
            <button
              onClick={onDesactivar}
              disabled={ocupado}
              className="p-1.5 rounded-lg text-red-600 hover:bg-red-50 transition-colors disabled:opacity-50"
              aria-label="Desactivar servicio"
              title="Desactivar"
            >
              <Power className="w-4 h-4" />
            </button>
          ) : (
            <button
              onClick={onReactivar}
              disabled={ocupado}
              className="p-1.5 rounded-lg text-emerald-700 hover:bg-emerald-50 transition-colors disabled:opacity-50"
              aria-label="Reactivar servicio"
              title="Reactivar"
            >
              <Power className="w-4 h-4" />
            </button>
          )}
        </div>
      )}
    </div>
  )
}

// ── Editor de un servicio (alta o edición) ───────────────────────────────────

function EditorServicio({
  borrador, setBorrador, guardando, onGuardar, onCancelar, textoGuardar,
}: {
  borrador: Borrador
  setBorrador: (b: Borrador) => void
  guardando: boolean
  onGuardar: () => void
  onCancelar: () => void
  textoGuardar: string
}) {
  const set = <K extends keyof Borrador>(key: K, value: Borrador[K]) =>
    setBorrador({ ...borrador, [key]: value })

  // Las claves SAT se muestran colapsadas: solo se necesitan para facturar.
  const [satAbierto, setSatAbierto] = useState(
    borrador.sat_product_key !== '' || borrador.sat_unit_key !== '',
  )

  return (
    <div
      className="rounded-2xl p-4 space-y-3"
      style={{ background: 'rgba(255,255,255,0.85)', border: '1px solid rgba(201,162,39,0.3)' }}
    >
      <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))' }}>
        <div className="sm:col-span-full">
          <label className="label">Nombre del servicio</label>
          <input
            className="input"
            maxLength={150}
            placeholder="Ej. Consulta general"
            value={borrador.name}
            onChange={e => set('name', e.target.value)}
          />
        </div>

        <div>
          <label className="label">Precio base (MXN)</label>
          <input
            className="input"
            type="number"
            min={0}
            step="0.01"
            placeholder="0.00"
            value={borrador.base_price}
            onChange={e => set('base_price', e.target.value)}
          />
        </div>
      </div>

      {/* Claves SAT — opcionales, colapsadas */}
      <div>
        <button
          type="button"
          onClick={() => setSatAbierto(o => !o)}
          className="flex items-center gap-1.5 text-xs font-medium text-amber-700 hover:text-amber-800 transition-colors"
        >
          <ChevronDown className={`w-3.5 h-3.5 transition-transform ${satAbierto ? 'rotate-180' : ''}`} />
          Claves SAT (opcional, para facturar)
        </button>
        {satAbierto && (
          <div className="grid gap-3 mt-2" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))' }}>
            <div>
              <label className="label">Clave de producto/servicio SAT</label>
              <input
                className="input"
                maxLength={255}
                placeholder="Ej. 85121800"
                value={borrador.sat_product_key}
                onChange={e => set('sat_product_key', e.target.value)}
              />
            </div>
            <div>
              <label className="label">Clave de unidad SAT</label>
              <input
                className="input"
                maxLength={255}
                placeholder="Ej. E48"
                value={borrador.sat_unit_key}
                onChange={e => set('sat_unit_key', e.target.value)}
              />
            </div>
          </div>
        )}
      </div>

      <div className="flex items-center justify-end gap-2 pt-1">
        <button className="btn-secondary" onClick={onCancelar} disabled={guardando}>
          <X className="w-4 h-4" /> Cancelar
        </button>
        <button className="btn-primary" onClick={onGuardar} disabled={guardando}>
          {guardando ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
          {textoGuardar}
        </button>
      </div>
    </div>
  )
}
