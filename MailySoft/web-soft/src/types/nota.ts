/** Tipos del dominio Notas y Tareas (reflejan apps/notas/serializers.py). */

export type NoteScope = 'personal' | 'role' | 'all'

export interface NoteAuthor {
  id: string
  full_name: string
}

/** Sede de un aviso; null = todas las sedes (aviso de toda la clínica). */
export interface NoteSucursal {
  id: string
  name: string
}

export interface Note {
  id: string
  author: NoteAuthor
  title: string
  body: string
  scope: NoteScope
  scope_display: string
  target_role: string
  is_task: boolean
  done: boolean
  remind_at: string | null // ISO UTC
  pinned: boolean
  /** Sede del aviso (multi-sede). null = todas las sedes. Los personales van null. */
  sucursal: NoteSucursal | null
  /** Aviso destacado. Solo el dueño puede marcarlo. */
  is_important: boolean
  created_at: string
  updated_at: string
}

export interface NoteCreateInput {
  title?: string
  body?: string
  scope?: NoteScope
  target_role?: string
  is_task?: boolean
  remind_at?: string | null
  pinned?: boolean
  /** Solo el dueño lo usa libremente: una sede, o null = todas. El resto queda forzado a su sede. */
  sucursal_id?: string | null
  /** Solo el dueño puede marcarlo. */
  is_important?: boolean
}

export type NoteUpdateInput = Partial<NoteCreateInput>
