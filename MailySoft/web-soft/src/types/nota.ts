/** Tipos del dominio Notas y Tareas (reflejan apps/notas/serializers.py). */

export type NoteScope = 'personal' | 'role' | 'all'

export interface NoteAuthor {
  id: string
  full_name: string
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
}

export type NoteUpdateInput = Partial<NoteCreateInput>
