/** Tipos del dominio Notificaciones (reflejan apps/notificaciones/serializers.py). */

export type NotificationKind = 'meeting' | 'team_note' | 'role_note' | 'broadcast'

/** Objeto destino al que apunta el clic. '' = sin destino. */
export type NotificationTarget = 'appointment' | 'agenda_block' | 'note' | ''

export interface NotificationActor {
  id: string
  full_name: string
}

export interface Notification {
  id: string
  actor: NotificationActor | null
  kind: NotificationKind
  kind_display: string
  title: string
  body: string
  target_type: NotificationTarget
  target_id: string | null
  read_at: string | null // ISO UTC
  is_read: boolean
  created_at: string
}
