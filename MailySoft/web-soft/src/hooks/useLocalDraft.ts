/**
 * useLocalDraft — AUTOGUARDADO como BORRADOR LOCAL (localStorage), genérico y
 * tipado. Protege el avance de un formulario si el usuario recarga, cierra por
 * error o lo deja a medias: al volver, recupera lo escrito.
 *
 * NO toca el servidor: la autoridad de los datos sigue siendo el backend. El
 * botón "Guardar" real de cada formulario no cambia; el borrador solo cubre el
 * avance sin guardar.
 *
 * Comportamiento:
 *   - Al montar: lee `localStorage[storageKey]`. Si existe y tiene contenido,
 *     lo expone como `draft` (con su `savedAt`). NO escribe todavía.
 *   - "Baseline": el valor del formulario que representa el estado del servidor.
 *     Se (re)captura cuando la vigilancia ARRANCA — es decir, cuando `enabled`
 *     pasa de false→true (el formulario ya cargó sus datos) o cuando cambia
 *     `storageKey` (se abrió otra entidad). Así, cargar datos del servidor NO
 *     cuenta como "cambio" y no genera borradores falsos.
 *   - Mientras `enabled`: con debounce, si `JSON.stringify(value)` difiere del
 *     baseline, persiste `{ data, savedAt }`. Si vuelve a ser igual al baseline,
 *     borra la clave (no dejar borradores vacíos/redundantes).
 *   - `clearDraft()`: elimina la clave e invalida el baseline, que se recaptura
 *     en el render siguiente contra el valor ya vigente (llamar en el onSuccess
 *     del Guardar real, o al Descartar).
 *   - Caducidad: un borrador con más de `DRAFT_TTL_MS` se ignora y se borra al
 *     leerlo (no dejar datos clínicos residuales en el equipo).
 *   - Defensivo: todo acceso a localStorage va en try/catch (modo privado /
 *     cuota); si falla, no rompe el formulario.
 */

import { useEffect, useMemo, useRef, useState } from 'react'

/**
 * Antigüedad máxima de un borrador (48 h). Pasado ese plazo se ignora y se borra
 * al leerlo: los borradores contienen datos clínicos y no deben quedar de forma
 * indefinida en el equipo (especialmente en consultorios con equipo compartido,
 * donde puede pasar mucho tiempo sin cerrar sesión).
 */
const DRAFT_TTL_MS = 48 * 60 * 60 * 1000

/** Borrador recuperado desde localStorage. */
export interface LocalDraft<T> {
  data: T
  /** ISO-8601 de cuándo se guardó el borrador. */
  savedAt: string
}

interface UseLocalDraftOptions<T> {
  /** Clave de localStorage (la arma el componente con draftKey()). */
  storageKey: string
  /** Estado editable actual del formulario. */
  value: T
  /**
   * Solo autoguarda mientras sea true. Debe volverse true SOLO cuando el
   * formulario ya cargó sus datos del servidor: ese flanco fija el baseline.
   */
  enabled: boolean
  /** Retardo del debounce en ms (default 800). */
  debounceMs?: number
}

interface UseLocalDraftResult<T> {
  /** Borrador encontrado al montar (o null si no había). */
  draft: LocalDraft<T> | null
  /** Borra el borrador y resetea el baseline al valor actual. */
  clearDraft: () => void
}

function leer(storageKey: string): string | null {
  if (typeof window === 'undefined') return null
  try {
    return localStorage.getItem(storageKey)
  } catch {
    return null
  }
}

function escribir(storageKey: string, valor: string): void {
  if (typeof window === 'undefined') return
  try {
    localStorage.setItem(storageKey, valor)
  } catch {
    // Cuota / modo privado: ignorar, el formulario sigue funcionando.
  }
}

function borrar(storageKey: string): void {
  if (typeof window === 'undefined') return
  try {
    localStorage.removeItem(storageKey)
  } catch {
    // Ignorar.
  }
}

export function useLocalDraft<T>({
  storageKey,
  value,
  enabled,
  debounceMs = 800,
}: UseLocalDraftOptions<T>): UseLocalDraftResult<T> {
  // Serialización estable del valor actual (una vez por render).
  const serialized = useMemo(() => {
    try {
      return JSON.stringify(value)
    } catch {
      return ''
    }
  }, [value])

  // Baseline = estado del servidor contra el que se comparan los cambios.
  const baselineRef = useRef<string | null>(null)
  const prevEnabledRef = useRef(false)

  // Borrador vigente, EMPAREJADO con su clave. Al cambiar la clave (se abrió
  // otra entidad/paciente/plan) se re-lee el borrador en el mismo render —sin
  // desfase de un ciclo— con el patrón de "ajustar estado al cambiar props".
  const [store, setStore] = useState<{ key: string; draft: LocalDraft<T> | null }>(
    () => ({ key: storageKey, draft: leerDraft<T>(storageKey) }),
  )
  let draft = store.draft
  if (store.key !== storageKey) {
    draft = leerDraft<T>(storageKey)
    setStore({ key: storageKey, draft })
    baselineRef.current = null // recapturar baseline con la nueva entidad
  }

  // Captura del baseline cuando arranca la vigilancia (enabled false→true) o
  // tras un cambio de clave (baseline reseteado a null). Es el estado "del
  // servidor" recién cargado; a partir de aquí, un cambio real sí es borrador.
  useEffect(() => {
    const arranca = enabled && !prevEnabledRef.current
    if ((arranca || baselineRef.current === null) && enabled) {
      baselineRef.current = serialized
    }
    prevEnabledRef.current = enabled
  }, [enabled, serialized])

  // Autoguardado con debounce.
  useEffect(() => {
    if (!enabled) return
    const timer = setTimeout(() => {
      const baseline = baselineRef.current
      if (baseline === null || serialized === baseline) {
        // Sin baseline aún, o volvió al estado del servidor: no dejar borrador.
        if (serialized === baseline) borrar(storageKey)
        return
      }
      const payload: LocalDraft<T> = { data: value, savedAt: new Date().toISOString() }
      try {
        escribir(storageKey, JSON.stringify(payload))
      } catch {
        // Serialización imposible: ignorar.
      }
    }, debounceMs)
    return () => clearTimeout(timer)
  }, [serialized, enabled, storageKey, debounceMs, value])

  // clearDraft estable (ref): borra la clave vigente e INVALIDA el baseline.
  //
  // El baseline NO se fija aquí con `serialized`: al "Descartar", el formulario
  // todavía contiene el borrador en este render y se revierte al servidor en el
  // mismo lote de actualizaciones. Fijarlo ahora dejaría baseline=borrador y
  // value=servidor → el debounce escribiría un borrador falso. Poniéndolo en
  // null, el efecto de captura lo re-toma en el render siguiente contra el valor
  // ya revertido, y mientras tanto el debounce no escribe nada.
  const clearDraftFn = useRef((): void => {})
  clearDraftFn.current = (): void => {
    borrar(storageKey)
    baselineRef.current = null
    setStore({ key: storageKey, draft: null })
  }

  return {
    draft,
    clearDraft: () => clearDraftFn.current(),
  }
}

/**
 * Lee el borrador de una clave, descartándolo (y borrándolo) si ya venció el
 * TTL o si su `savedAt` no es una fecha válida.
 */
function leerDraft<T>(storageKey: string): LocalDraft<T> | null {
  const parsed = parseDraft<T>(leer(storageKey))
  if (parsed === null) return null
  const savedAtMs = new Date(parsed.savedAt).getTime()
  if (!Number.isFinite(savedAtMs) || Date.now() - savedAtMs > DRAFT_TTL_MS) {
    borrar(storageKey)
    return null
  }
  return parsed
}

/** Parsea un borrador de localStorage con validación mínima de forma. */
function parseDraft<T>(raw: string | null): LocalDraft<T> | null {
  if (raw === null || raw === '' || raw === 'null' || raw === 'undefined') return null
  try {
    const parsed = JSON.parse(raw) as unknown
    if (
      parsed !== null &&
      typeof parsed === 'object' &&
      'data' in parsed &&
      'savedAt' in parsed &&
      typeof (parsed as { savedAt: unknown }).savedAt === 'string'
    ) {
      const p = parsed as { data: T; savedAt: string }
      return { data: p.data, savedAt: p.savedAt }
    }
    return null
  } catch {
    return null
  }
}
