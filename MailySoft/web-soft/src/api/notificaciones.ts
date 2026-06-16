/** api/notificaciones — campana de avisos. Todo pasa por el cliente http central. */

import { request } from '../lib/http'
import type { Paginated } from '../types/paciente'
import type { Notification } from '../types/notificacion'

/** GET /notificaciones/ — mis notificaciones (más recientes primero). */
export async function listNotifications(
  params: { only_unread?: boolean } = {},
): Promise<Paginated<Notification>> {
  const qs = new URLSearchParams()
  if (params.only_unread) qs.set('only_unread', 'true')
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return request<Paginated<Notification>>(`/notificaciones/${suffix}`)
}

/** GET /notificaciones/conteo/ — cuántas no leídas tengo (barato; para el badge). */
export async function getUnreadCount(): Promise<{ unread: number }> {
  return request<{ unread: number }>('/notificaciones/conteo/')
}

/** POST /notificaciones/<id>/leida/ — marca una como leída. */
export async function markNotificationRead(id: string): Promise<Notification> {
  return request<Notification>(`/notificaciones/${id}/leida/`, { method: 'POST' })
}

/** POST /notificaciones/leidas/ — marca todas como leídas. */
export async function markAllNotificationsRead(): Promise<{ updated: number }> {
  return request<{ updated: number }>('/notificaciones/leidas/', { method: 'POST' })
}
