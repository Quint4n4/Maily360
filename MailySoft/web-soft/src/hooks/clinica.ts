/**
 * Hooks de TanStack Query para "Mi Consultorio".
 * Centralizan query keys e invalidación de caché tras cada mutación.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { listDoctors } from '../api/personal'
import type { Doctor } from '../types/personal'
import {
  createCategory,
  createCredential,
  createTemplate,
  createUniversity,
  deleteCategory,
  deleteCredential,
  deleteTemplate,
  deleteUniversity,
  getClinicSettings,
  listCategories,
  listCredentials,
  listTemplates,
  listUniversities,
  updateClinicSettings,
  updateDoctorProfile,
  updateTemplate,
} from '../api/clinica'
import type {
  ClinicSettingsUpdateInput,
  ClinicTemplateCreateInput,
  ClinicTemplateUpdateInput,
  DoctorProfileUpdateInput,
  DoctorUniversityCreateInput,
  PatientCategoryCreateInput,
  TemplateKind,
} from '../types/clinica'
import type { DoctorCredentialCreateInput } from '../types/credenciales'

/** Claves de caché. Todo lo de "Mi Consultorio" cuelga de ['clinica']. */
export const clinicaKeys = {
  all: ['clinica'] as const,
  settings: ['clinica', 'settings'] as const,
  templates: (kind?: TemplateKind) => ['clinica', 'templates', kind ?? 'all'] as const,
  categories: ['clinica', 'categories'] as const,
  universities: (doctorId: string) => ['clinica', 'universities', doctorId] as const,
  credentials: (doctorId: string) => ['clinica', 'credentials', doctorId] as const,
}

/* ─── Configuración ───────────────────────────────────────────────────────── */

export function useClinicSettings() {
  return useQuery({
    queryKey: clinicaKeys.settings,
    queryFn: getClinicSettings,
  })
}

export function useUpdateClinicSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: ClinicSettingsUpdateInput) => updateClinicSettings(input),
    onSuccess: (data) => {
      qc.setQueryData(clinicaKeys.settings, data)
    },
  })
}

/* ─── Plantillas ──────────────────────────────────────────────────────────── */

export function useTemplates(kind?: TemplateKind) {
  return useQuery({
    queryKey: clinicaKeys.templates(kind),
    queryFn: () => listTemplates(kind),
  })
}

export function useCreateTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: ClinicTemplateCreateInput) => createTemplate(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['clinica', 'templates'] }),
  })
}

export function useUpdateTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: ClinicTemplateUpdateInput }) =>
      updateTemplate(id, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['clinica', 'templates'] }),
  })
}

export function useDeleteTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => deleteTemplate(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['clinica', 'templates'] }),
  })
}

/* ─── Categorías ──────────────────────────────────────────────────────────── */

export function useCategories() {
  return useQuery({
    queryKey: clinicaKeys.categories,
    queryFn: listCategories,
  })
}

export function useCreateCategory() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: PatientCategoryCreateInput) => createCategory(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: clinicaKeys.categories }),
  })
}

export function useDeleteCategory() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => deleteCategory(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: clinicaKeys.categories }),
  })
}

/* ─── Perfil del médico ───────────────────────────────────────────────────── */

/**
 * Perfil del médico actual (incluye sello/foto/cédulas del perfil ampliado).
 * Lo resuelve listando los doctores del tenant y filtrando por `doctorId`,
 * que viene de /me/ (user.doctor_id). Devuelve null si no hay médico asociado.
 */
export function useDoctorActual(doctorId: string | null) {
  return useQuery({
    queryKey: ['clinica', 'doctor-actual', doctorId ?? ''],
    queryFn: async (): Promise<Doctor | null> => {
      const page = await listDoctors(true)
      return page.results.find((d) => d.id === doctorId) ?? null
    },
    enabled: !!doctorId,
  })
}

export function useUpdateDoctorProfile(doctorId: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: DoctorProfileUpdateInput) => {
      if (!doctorId) throw new Error('No hay un médico asociado a tu cuenta.')
      return updateDoctorProfile(doctorId, input)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['clinica', 'doctor-actual'] })
      qc.invalidateQueries({ queryKey: ['personal'] })
    },
  })
}

/* ─── Universidades del médico ────────────────────────────────────────────── */

export function useUniversities(doctorId: string | null) {
  return useQuery({
    queryKey: clinicaKeys.universities(doctorId ?? ''),
    queryFn: () => listUniversities(doctorId as string),
    enabled: !!doctorId,
  })
}

export function useCreateUniversity(doctorId: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: DoctorUniversityCreateInput) => {
      if (!doctorId) throw new Error('No hay un médico asociado a tu cuenta.')
      return createUniversity(doctorId, input)
    },
    onSuccess: () => {
      if (doctorId) qc.invalidateQueries({ queryKey: clinicaKeys.universities(doctorId) })
    },
  })
}

export function useDeleteUniversity(doctorId: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (universityId: string) => deleteUniversity(universityId),
    onSuccess: () => {
      if (doctorId) qc.invalidateQueries({ queryKey: clinicaKeys.universities(doctorId) })
    },
  })
}

/* ─── Credenciales del médico (COFEPRIS F2) ───────────────────────────────── */

export function useCredentials(doctorId: string | null) {
  return useQuery({
    queryKey: clinicaKeys.credentials(doctorId ?? ''),
    queryFn: () => listCredentials(doctorId as string),
    enabled: !!doctorId,
  })
}

export function useCreateCredential(doctorId: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: DoctorCredentialCreateInput) => {
      if (!doctorId) throw new Error('No hay un médico asociado a tu cuenta.')
      return createCredential(doctorId, input)
    },
    onSuccess: () => {
      if (doctorId) qc.invalidateQueries({ queryKey: clinicaKeys.credentials(doctorId) })
    },
  })
}

export function useDeleteCredential(doctorId: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (credentialId: string) => deleteCredential(credentialId),
    onSuccess: () => {
      if (doctorId) qc.invalidateQueries({ queryKey: clinicaKeys.credentials(doctorId) })
    },
  })
}
