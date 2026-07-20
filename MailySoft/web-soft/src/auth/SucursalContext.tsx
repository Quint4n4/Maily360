/**
 * SucursalContext — dueño de la SUCURSAL ACTIVA en el frontend (multi-sede).
 *
 * Fuente de verdad de las sedes PERMITIDAS: /me.sucursales (vía AuthContext).
 * Al entrar, la sucursal activa se inicializa tomando la `is_default` (o la
 * primera), salvo que el usuario ya tuviera una elección persistida válida (una
 * sede concreta, o "Todas las sucursales"). La elección se guarda en
 * localStorage (clave `maily.sucursal`, vía sucursalStore) para que el cliente
 * http mande `X-Sucursal-Id` y para recordar la preferencia entre recargas.
 *
 * Fase 3 (finanzas por sucursal): existe la opción "Todas las sucursales"
 * (consolidado), disponible SOLO si el usuario tiene más de una sede permitida.
 * En ese modo `activeSucursalId` es null → el cliente http NO manda el header y
 * el backend filtra a las sedes permitidas del usuario (dueño → consolidado;
 * admin de sede → solo la suya). OJO: el estado de cuenta POR PACIENTE nunca se
 * filtra por sede (es compartido); solo caja/reportes/dashboard son privados de
 * cada sede.
 *
 * Al cambiar de sucursal se invalidan las queries dependientes (personal,
 * consultorios, agenda, finanzas) para que se refresquen con la nueva sede y no
 * se sirva caché de otra sucursal. El backend es la autoridad: filtra por el
 * header; la UI solo refleja el resultado.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import { useAuth } from './AuthContext'
import { queryClient } from '../lib/queryClient'
import {
  getSeleccionSucursal,
  setSeleccionSucursal,
  type SeleccionSucursal,
} from '../lib/sucursalStore'
import type { SucursalBrief } from '../types/sucursal'

interface SucursalContextValue {
  /** Sucursales permitidas del usuario (de /me). Vacío si la clínica no las usa. */
  sucursales: SucursalBrief[]
  /**
   * Id de la sede activa, o null cuando se ve el CONSOLIDADO ("todas") o el
   * usuario no tiene sedes. Para distinguir ambos casos, usa `esTodas`.
   */
  activeSucursalId: string | null
  /** La sucursal activa resuelta (brief), o null en modo "todas" / sin sedes. */
  activeSucursal: SucursalBrief | null
  /** true si la vista activa es el consolidado "Todas las sucursales". */
  esTodas: boolean
  /** true si el usuario puede elegir "Todas las sucursales" (más de una sede). */
  puedeVerTodas: boolean
  /** Cambia la sede activa (id) o pasa al consolidado (null): persiste + refresca. */
  setActiveSucursal: (id: string | null) => void
}

const SucursalContext = createContext<SucursalContextValue | null>(null)

/** Elige la sucursal por defecto de una lista: la `is_default`, o la primera. */
function elegirDefault(lista: SucursalBrief[]): SeleccionSucursal {
  if (lista.length === 0) return null
  const principal = lista.find((s) => s.is_default)
  return { modo: 'sede', id: (principal ?? lista[0]).id }
}

/** Comparación estructural de selecciones (evita re-escrituras innecesarias). */
function mismaSeleccion(a: SeleccionSucursal, b: SeleccionSucursal): boolean {
  if (a === null || b === null) return a === b
  if (a.modo === 'todas' || b.modo === 'todas') return a.modo === b.modo
  return a.id === b.id
}

export function SucursalProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const sucursales = useMemo<SucursalBrief[]>(() => user?.sucursales ?? [], [user])

  // Estado local: arranca de lo persistido; se reconcilia contra las permitidas.
  const [seleccion, setSeleccionState] = useState<SeleccionSucursal>(() => getSeleccionSucursal())

  // Reconciliar cuando cambia el conjunto de sucursales permitidas (login,
  // recarga, cambio de clínica): si la sede persistida ya no es válida (o no
  // hay), tomar la `is_default`. "Todas" solo es válida con más de una sede.
  // Depender de los ids evita re-ejecutar cuando la lista se recrea igual.
  const idsKey = sucursales.map((s) => s.id).join(',')
  useEffect(() => {
    const guardada = getSeleccionSucursal()
    const valida =
      guardada !== null &&
      (guardada.modo === 'todas'
        ? sucursales.length > 1
        : sucursales.some((s) => s.id === guardada.id))
    const siguiente = valida ? guardada : elegirDefault(sucursales)
    if (!mismaSeleccion(siguiente, guardada)) setSeleccionSucursal(siguiente)
    setSeleccionState(siguiente)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idsKey])

  const setActiveSucursal = useCallback((id: string | null) => {
    const siguiente: SeleccionSucursal = id === null ? { modo: 'todas' } : { modo: 'sede', id }
    if (mismaSeleccion(siguiente, getSeleccionSucursal())) return
    setSeleccionSucursal(siguiente)
    setSeleccionState(siguiente)
    // Refrescar los datos scoping-eados por sede (el backend filtra por header).
    // Finanzas incluida: caja/reportes/dashboard son privados por sede. El estado
    // de cuenta por paciente es compartido; invalidarlo solo lo vuelve a pedir
    // (el backend devuelve lo mismo), así que no hay riesgo de datos cruzados.
    void queryClient.invalidateQueries({ queryKey: ['personal'] })
    void queryClient.invalidateQueries({ queryKey: ['agenda'] })
    void queryClient.invalidateQueries({ queryKey: ['finanzas'] })
  }, [])

  const activeSucursalId = seleccion !== null && seleccion.modo === 'sede' ? seleccion.id : null
  const esTodas = seleccion !== null && seleccion.modo === 'todas'
  const puedeVerTodas = sucursales.length > 1

  const activeSucursal = useMemo<SucursalBrief | null>(
    () => sucursales.find((s) => s.id === activeSucursalId) ?? null,
    [sucursales, activeSucursalId],
  )

  const value: SucursalContextValue = {
    sucursales,
    activeSucursalId,
    activeSucursal,
    esTodas,
    puedeVerTodas,
    setActiveSucursal,
  }

  return <SucursalContext.Provider value={value}>{children}</SucursalContext.Provider>
}

export function useSucursalActiva(): SucursalContextValue {
  const ctx = useContext(SucursalContext)
  if (ctx === null) throw new Error('useSucursalActiva debe usarse dentro de <SucursalProvider>')
  return ctx
}
