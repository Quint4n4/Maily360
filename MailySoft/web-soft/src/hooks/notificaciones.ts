/** Hooks de TanStack Query para la campana de notificaciones. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  getUnreadCount,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from '../api/notificaciones'

const notifKey = ['notificaciones'] as const

/** Polling de avisos: "casi en vivo" → revisa cada 30s (decisión del proyecto). */
const POLL_MS = 30_000

/** Conteo de no leídas para el badge de la campana. Refresca solo cada 30s. */
export function useUnreadCount(enabled = true) {
  return useQuery({
    queryKey: [...notifKey, 'conteo'],
    queryFn: getUnreadCount,
    enabled,
    refetchInterval: POLL_MS,
    refetchIntervalInBackground: false,
  })
}

/** Lista de mis notificaciones (solo se consulta cuando el menú está abierto). */
export function useNotifications(opts: { onlyUnread?: boolean; enabled?: boolean } = {}) {
  const { onlyUnread = false, enabled = true } = opts
  return useQuery({
    queryKey: [...notifKey, 'list', { onlyUnread }],
    queryFn: () => listNotifications({ only_unread: onlyUnread }),
    enabled,
  })
}

export function useMarkNotificationRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => markNotificationRead(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: notifKey }),
  })
}

export function useMarkAllNotificationsRead() {
  const qc = useQueryClient()
  return useMutation({
    // sin argumentos → mutate() se llama sin parámetros
    mutationFn: () => markAllNotificationsRead(),
    onSuccess: () => qc.invalidateQueries({ queryKey: notifKey }),
  })
}
