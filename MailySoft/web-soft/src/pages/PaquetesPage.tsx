import { useEffect, useMemo, useState } from 'react'
import { Package, Lock, Plus, Trash2, Loader2, Save, X, Pencil, AlertTriangle } from 'lucide-react'

import Topbar from '../components/Topbar'
import { useRole } from '../auth/RoleContext'
import { useSucursalActiva } from '../auth/SucursalContext'
import { useConcepts } from '../hooks/finanzas'
import type { ServiceConcept } from '../api/finanzas'
import {
  usePaquetes,
  usePaquete,
  useCrearPaquete,
  useGuardarPaquete,
  useEliminarPaquete,
} from '../hooks/paquetes'
import type { PackageItemInput, PackageListItem } from '../types/paquetes'
import { errorMsg } from '../lib/apiErrors'
import { formatMoney } from '../lib/format'
import { useAviso, useConfirm } from '../components/common/DialogProvider'
import { BadgeSedes, SelectorSedes } from '../components/common/SelectorSedes'

const ORO = '#C9A227'
const MAX_SESIONES = 52

/** Renglón en edición: concepto del catálogo + nº de sesiones (string controlado). */
interface DraftRow {
  concept_id: string
  sessions: string
}

interface Draft {
  name: string
  description: string
  is_active: boolean
  rows: DraftRow[]
  /** Sedes donde estará disponible (multi-sede). Vacío = todas las sedes. */
  sucursal_ids: string[]
}

const emptyRow = (): DraftRow => ({ concept_id: '', sessions: '1' })

const emptyDraft = (): Draft => ({
  name: '',
  description: '',
  is_active: true,
  rows: [emptyRow()],
  sucursal_ids: [],
})

export default function PaquetesPage() {
  const { role } = useRole()
  // Ver (solo lectura) = dueño o admin; EDITAR (crear/editar/borrar) = solo dueño.
  // El backend es la autoridad: al admin le da 403 en las mutaciones, pero GET
  // sigue abierto para que pueda ver el catálogo al cotizar/calendarizar.
  const puedeVer = role === 'owner' || role === 'admin'
  const puedeEditar = role === 'owner'

  return (
    <div className="min-h-screen relative">
      <div className="fixed inset-0 -z-10" style={{ background: 'linear-gradient(135deg, #b89a52 0%, #d8c690 45%, #f1e8cf 100%)' }} />
      <div className="fixed inset-0 -z-10 bg-cover bg-center" style={{ backgroundImage: "url('/fondo-agenda.jpg')" }} />
      <div className="fixed inset-0 -z-10" style={{ background: 'rgba(255,255,255,0.20)' }} />
      <Topbar active="paquetes" />

      <main className="max-w-4xl mx-auto px-4 md:px-6 py-6 space-y-5">
        <div className="glass-card rounded-2xl px-6 py-5 flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2" style={{ color: '#2A241B' }}>
              <Package className="w-6 h-6" style={{ color: ORO }} />
              Paquetes
            </h1>
            <p className="text-sm" style={{ color: '#7A756C' }}>
              Arma paquetes reutilizables de tratamientos para cotizar o calendarizar de un solo paso.
            </p>
          </div>
        </div>

        {!puedeVer ? (
          <div className="glass-card rounded-2xl p-10 text-center">
            <Lock className="w-8 h-8 mx-auto mb-3" style={{ color: '#9A958C' }} />
            <p className="text-sm" style={{ color: '#7A756C' }}>
              Tu rol (<strong>{role}</strong>) no puede ver los paquetes. Solo el Dueño y el Administrador.
            </p>
          </div>
        ) : (
          <PaquetesManager puedeEditar={puedeEditar} />
        )}
      </main>
    </div>
  )
}

/* ── Gestión (solo owner/admin) ──────────────────────────────────────────────── */

function PaquetesManager({ puedeEditar }: { puedeEditar: boolean }) {
  const aviso = useAviso()
  const confirmar = useConfirm()
  // Sedes permitidas del usuario (vacío = la clínica no usa multi-sede).
  const { sucursales } = useSucursalActiva()
  const usaSucursales = sucursales.length > 0

  const lista = usePaquetes({ onlyActive: false })
  const conceptsQuery = useConcepts({ includeInactive: true })
  const concepts: ServiceConcept[] = conceptsQuery.data?.results ?? []

  const crear = useCrearPaquete()
  const eliminar = useEliminarPaquete()

  // Editor: null = cerrado; 'new' = alta; un id = edición de ese paquete.
  const [editId, setEditId] = useState<string | 'new' | null>(null)
  const detalle = usePaquete(
    editId && editId !== 'new' ? editId : null,
    Boolean(editId && editId !== 'new'),
  )
  const guardar = useGuardarPaquete(editId && editId !== 'new' ? editId : '')

  const [draft, setDraft] = useState<Draft>(emptyDraft())
  const [loadedId, setLoadedId] = useState<string | null>(null)

  // Al abrir "Nuevo": limpia el editor.
  useEffect(() => {
    if (editId === 'new') {
      setDraft(emptyDraft())
      setLoadedId(null)
    }
  }, [editId])

  // Al cargar el detalle de un paquete existente: llena el editor.
  useEffect(() => {
    if (editId && editId !== 'new' && detalle.data && detalle.data.id !== loadedId) {
      setDraft({
        name: detalle.data.name,
        description: detalle.data.description,
        is_active: detalle.data.is_active,
        rows: detalle.data.items.length
          ? detalle.data.items.map((it) => ({ concept_id: it.concept_id, sessions: String(it.sessions) }))
          : [emptyRow()],
        sucursal_ids: detalle.data.sucursales.map((s) => s.id),
      })
      setLoadedId(detalle.data.id)
    }
  }, [editId, detalle.data, loadedId])

  const conceptById = useMemo(() => {
    const m = new Map<string, ServiceConcept>()
    for (const c of concepts) m.set(c.id, c)
    return m
  }, [concepts])

  /** Precio en vivo del borrador: Σ (precio base del concepto × sesiones). */
  const draftPrice = useMemo(
    () =>
      draft.rows.reduce((acc, r) => {
        const c = conceptById.get(r.concept_id)
        const base = c ? Number(c.base_price) : 0
        return acc + base * Number(r.sessions || 0)
      }, 0),
    [draft.rows, conceptById],
  )

  const paquetes: PackageListItem[] = lista.data?.results ?? []

  const setRow = (i: number, patch: Partial<DraftRow>): void =>
    setDraft((p) => ({ ...p, rows: p.rows.map((x, j) => (j === i ? { ...x, ...patch } : x)) }))

  const addRow = (): void => setDraft((p) => ({ ...p, rows: [...p.rows, emptyRow()] }))
  const removeRow = (i: number): void =>
    setDraft((p) => ({ ...p, rows: p.rows.filter((_, j) => j !== i) }))

  const cerrarEditor = (): void => {
    setEditId(null)
    setDraft(emptyDraft())
    setLoadedId(null)
  }

  const buildItems = (): PackageItemInput[] =>
    draft.rows
      .filter((r) => r.concept_id)
      .map((r, i) => ({
        concept_id: r.concept_id,
        sessions: Math.max(1, Math.min(MAX_SESIONES, Math.floor(Number(r.sessions) || 1))),
        order: i,
      }))

  const onGuardar = (): void => {
    const name = draft.name.trim()
    if (!name) {
      void aviso({ mensaje: 'Ponle un nombre al paquete.', tipo: 'info' })
      return
    }
    const items = buildItems()
    if (items.length === 0) {
      void aviso({ mensaje: 'Agrega al menos un tratamiento al paquete.', tipo: 'info' })
      return
    }
    // Vacío = "todas las sedes" (convención del backend).
    const sucursal_ids = draft.sucursal_ids
    if (editId === 'new') {
      crear.mutate(
        { name, description: draft.description.trim(), is_active: draft.is_active, items, sucursal_ids },
        {
          onSuccess: () => {
            void aviso({ mensaje: 'Paquete creado.', tipo: 'exito' })
            cerrarEditor()
          },
          onError: (e) => void aviso({ mensaje: errorMsg(e), tipo: 'error' }),
        },
      )
    } else {
      guardar.mutate(
        { name, description: draft.description.trim(), is_active: draft.is_active, items, sucursal_ids },
        {
          onSuccess: () => {
            void aviso({ mensaje: 'Paquete guardado.', tipo: 'exito' })
            cerrarEditor()
          },
          onError: (e) => void aviso({ mensaje: errorMsg(e), tipo: 'error' }),
        },
      )
    }
  }

  const onEliminar = async (p: PackageListItem): Promise<void> => {
    const ok = await confirmar({
      titulo: 'Eliminar paquete',
      mensaje: `¿Seguro que quieres eliminar el paquete «${p.name}»? Esta acción no se puede deshacer.`,
      textoConfirmar: 'Eliminar',
      peligro: true,
    })
    if (!ok) return
    eliminar.mutate(p.id, {
      onSuccess: () => {
        if (editId === p.id) cerrarEditor()
      },
      onError: (e) => void aviso({ mensaje: errorMsg(e), tipo: 'error' }),
    })
  }

  const guardando = crear.isPending || guardar.isPending

  return (
    <div className="space-y-4">
      {/* Barra: crear */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h2 className="text-base font-bold" style={{ color: '#2A241B' }}>
          Catálogo de paquetes
        </h2>
        {puedeEditar && editId === null && (
          <button
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-60"
            style={{ background: ORO, boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
            onClick={() => setEditId('new')}
          >
            <Plus className="w-4 h-4" /> Nuevo paquete
          </button>
        )}
      </div>

      {/* Editor (alta o edición) — solo el dueño */}
      {puedeEditar && editId !== null && (
        <div
          className="rounded-2xl p-4 space-y-4"
          style={{ background: 'rgba(255,255,255,0.7)', border: '1px solid rgba(201,162,39,0.18)' }}
        >
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold" style={{ color: '#2A241B' }}>
              {editId === 'new' ? 'Nuevo paquete' : 'Editar paquete'}
            </h3>
            <button className="p-1 rounded hover:bg-black/5" onClick={cerrarEditor} title="Cerrar">
              <X className="w-4 h-4" style={{ color: '#7A756C' }} />
            </button>
          </div>

          {editId !== 'new' && detalle.isLoading ? (
            <div className="flex items-center justify-center py-10" style={{ color: '#9A958C' }}>
              <Loader2 className="w-5 h-5 animate-spin" />
            </div>
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-[1fr_160px]">
                <div>
                  <label className="text-[11px] font-medium" style={{ color: '#9A958C' }}>Nombre</label>
                  <input
                    className="input"
                    placeholder="Nombre del paquete"
                    maxLength={200}
                    value={draft.name}
                    onChange={(e) => setDraft((p) => ({ ...p, name: e.target.value }))}
                  />
                </div>
                <div>
                  <label className="text-[11px] font-medium" style={{ color: '#9A958C' }}>Estado</label>
                  <label className="input flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={draft.is_active}
                      onChange={(e) => setDraft((p) => ({ ...p, is_active: e.target.checked }))}
                    />
                    <span className="text-sm" style={{ color: '#2A241B' }}>
                      {draft.is_active ? 'Activo' : 'Inactivo'}
                    </span>
                  </label>
                </div>
              </div>

              <div>
                <label className="text-[11px] font-medium" style={{ color: '#9A958C' }}>Descripción</label>
                <textarea
                  className="input"
                  rows={2}
                  placeholder="Descripción del paquete (opcional)"
                  maxLength={2000}
                  value={draft.description}
                  onChange={(e) => setDraft((p) => ({ ...p, description: e.target.value }))}
                />
              </div>

              {/* Sucursales donde está disponible (solo si la clínica usa multi-sede) */}
              <SelectorSedes
                sucursales={sucursales}
                seleccion={draft.sucursal_ids}
                onChange={(ids) => setDraft((p) => ({ ...p, sucursal_ids: ids }))}
                disabled={guardando}
              />

              {/* Tabla de tratamientos */}
              <div className="space-y-2">
                <label className="text-[11px] font-medium" style={{ color: '#9A958C' }}>Tratamientos</label>
                {draft.rows.map((r, i) => {
                  const c = conceptById.get(r.concept_id)
                  const importe = (c ? Number(c.base_price) : 0) * Number(r.sessions || 0)
                  return (
                    <div key={i} className="grid gap-2 items-end md:grid-cols-[2fr_90px_120px_28px]">
                      <div>
                        <select
                          className="input"
                          value={r.concept_id}
                          onChange={(e) => setRow(i, { concept_id: e.target.value })}
                          disabled={conceptsQuery.isLoading}
                        >
                          <option value="">Elige un tratamiento…</option>
                          {concepts.map((cc) => (
                            <option key={cc.id} value={cc.id}>
                              {cc.name}{cc.is_active ? '' : ' (inactivo)'}
                            </option>
                          ))}
                        </select>
                      </div>
                      <input
                        className="input text-right"
                        type="number"
                        min={1}
                        max={MAX_SESIONES}
                        placeholder="Sesiones"
                        value={r.sessions}
                        onChange={(e) => setRow(i, { sessions: e.target.value })}
                      />
                      <span className="text-sm text-right font-medium self-center" style={{ color: '#2A241B' }}>
                        {formatMoney(importe)}
                      </span>
                      {draft.rows.length > 1 ? (
                        <button
                          className="p-1 rounded hover:bg-red-50 justify-self-center"
                          onClick={() => removeRow(i)}
                          title="Quitar renglón"
                        >
                          <Trash2 className="w-4 h-4" style={{ color: '#B91C1C' }} />
                        </button>
                      ) : (
                        <span />
                      )}
                    </div>
                  )
                })}
                <button
                  className="inline-flex items-center gap-1.5 text-sm font-medium px-3 py-2 rounded-xl transition-colors hover:bg-black/5"
                  style={{ color: '#854F0B', border: '1px dashed rgba(201,162,39,0.4)' }}
                  onClick={addRow}
                >
                  <Plus className="w-4 h-4" /> Agregar tratamiento
                </button>
              </div>

              {/* Total + guardar */}
              <div className="flex items-center justify-between flex-wrap gap-3 pt-2 border-t" style={{ borderColor: 'rgba(0,0,0,0.06)' }}>
                <span className="text-base font-bold" style={{ color: '#2A241B' }}>
                  Precio: {formatMoney(draftPrice)}
                </span>
                <button
                  className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-60"
                  style={{ background: ORO, boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
                  onClick={onGuardar}
                  disabled={guardando}
                >
                  {guardando ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                  Guardar
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {/* Lista de paquetes */}
      {lista.isLoading ? (
        <div className="flex items-center justify-center py-16" style={{ color: '#9A958C' }}>
          <Loader2 className="w-6 h-6 animate-spin" />
        </div>
      ) : lista.isError ? (
        <div
          className="rounded-2xl px-5 py-4 text-sm font-semibold text-red-700"
          style={{ background: 'rgba(192,57,43,0.08)', border: '1px solid rgba(192,57,43,0.28)' }}
        >
          {errorMsg(lista.error)}
        </div>
      ) : paquetes.length === 0 ? (
        <div
          className="rounded-2xl px-6 py-10 text-center"
          style={{ background: 'rgba(255,255,255,0.7)', border: '1px dashed rgba(201,162,39,0.35)' }}
        >
          <Package className="w-8 h-8 mx-auto mb-2" style={{ color: ORO }} />
          <p className="text-sm font-medium" style={{ color: '#2A241B' }}>Aún no hay paquetes.</p>
          <p className="text-xs mt-1" style={{ color: '#7A756C' }}>
            Crea uno con «Nuevo paquete» para reutilizarlo en cotizaciones y calendarizaciones.
          </p>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {paquetes.map((p) => (
            <div
              key={p.id}
              className="rounded-2xl p-4"
              style={{ background: 'rgba(255,255,255,0.7)', border: '1px solid rgba(201,162,39,0.18)' }}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-semibold truncate" style={{ color: '#2A241B' }}>{p.name}</span>
                    {!p.is_active && (
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold" style={{ background: 'rgba(0,0,0,0.05)', color: '#7A756C' }}>
                        Inactivo
                      </span>
                    )}
                  </div>
                  {p.description && (
                    <p className="text-xs mt-0.5 line-clamp-2" style={{ color: '#7A756C' }}>{p.description}</p>
                  )}
                  {/* Un paquete sin tratamientos no sirve para cotizar: se avisa
                      aquí en vez de dejar solo un "$0.00" que pasa desapercibido. */}
                  {p.items_count === 0 ? (
                    <p className="text-[11px] mt-1 inline-flex items-center gap-1 font-semibold" style={{ color: '#B45309' }}>
                      <AlertTriangle className="w-3 h-3 shrink-0" />
                      Sin tratamientos — edítalo para agregarlos
                    </p>
                  ) : (
                    <p className="text-[11px] mt-1" style={{ color: '#9A958C' }}>
                      {p.items_count} tratamiento{p.items_count === 1 ? '' : 's'} · {p.sessions_total} sesión{p.sessions_total === 1 ? '' : 'es'}
                    </p>
                  )}
                  {usaSucursales && (
                    <div className="mt-1.5">
                      <BadgeSedes sucursales={p.sucursales} />
                    </div>
                  )}
                </div>
                <span className="text-sm font-bold whitespace-nowrap" style={{ color: ORO }}>{formatMoney(p.price)}</span>
              </div>
              {puedeEditar && (
                <div className="flex items-center gap-2 mt-3 pt-2 border-t" style={{ borderColor: 'rgba(0,0,0,0.06)' }}>
                  <button
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors hover:bg-black/5"
                    style={{ color: '#854F0B', border: '1px solid rgba(201,162,39,0.3)' }}
                    onClick={() => setEditId(p.id)}
                  >
                    <Pencil className="w-3.5 h-3.5" /> Editar
                  </button>
                  <button
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors hover:bg-red-50 disabled:opacity-60"
                    style={{ color: '#B91C1C', border: '1px solid rgba(185,28,28,0.25)' }}
                    onClick={() => onEliminar(p)}
                    disabled={eliminar.isPending}
                  >
                    <Trash2 className="w-3.5 h-3.5" /> Eliminar
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
