/** api/miembros — gestión de miembros de la clínica (solo Dueño/Admin). */

import { request } from '../lib/http'
import type { Member, MemberCreateInput, MemberUpdateInput } from '../types/personal'

/** GET /miembros/ — lista (sin paginar) de miembros del tenant. */
export async function listMembers(): Promise<Member[]> {
  return request<Member[]>('/miembros/')
}

/** POST /miembros/ — alta de miembro (usuario + membresía con rol). */
export async function createMember(input: MemberCreateInput): Promise<Member> {
  return request<Member>('/miembros/', { method: 'POST', body: input })
}

/** PATCH /miembros/<id>/ — cambia rol y/o bloquea/reactiva. */
export async function updateMember(id: string, input: MemberUpdateInput): Promise<Member> {
  return request<Member>(`/miembros/${id}/`, { method: 'PATCH', body: input })
}

/** POST /miembros/<id>/avatar/ — sube/reemplaza la foto del miembro (multipart). */
export async function uploadMemberAvatar(id: string, file: File): Promise<Member> {
  const fd = new FormData()
  fd.append('avatar', file)
  return request<Member>(`/miembros/${id}/avatar/`, { method: 'POST', body: fd })
}
