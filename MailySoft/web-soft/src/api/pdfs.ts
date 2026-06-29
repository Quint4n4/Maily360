/**
 * Cliente del flujo de PDFs asíncronos (Celery) — infra compartida (apps.pdfs).
 *
 * Cualquier PDF de la app se genera en 2º plano: un endpoint ENCOLA (devuelve
 * { job_id, status }), el front hace polling de /pdfs/job/<id>/ cada ~2 s y, al
 * estar "done", descarga /pdfs/job/<id>/file/. `pdfJobBlob` envuelve todo eso y
 * devuelve un Blob (firma idéntica a un fetch directo), así VisorPdf no cambia.
 */

import { request, requestBlob } from '../lib/http'

const _sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms))

interface PdfJobRef {
  job_id: string
  status: 'pending' | 'processing' | 'done' | 'failed'
}

/**
 * Encola un PDF, hace polling de su estado y descarga el resultado como Blob.
 *
 * @param enqueueUrl ruta del endpoint que encola y devuelve { job_id, status }
 *                   (p. ej. `/expediente/<id>/libro/pdf/?modo=completo`).
 */
export async function pdfJobBlob(enqueueUrl: string): Promise<Blob> {
  const job = await request<PdfJobRef>(enqueueUrl)

  let status = job.status
  const MAX_TRIES = 30 // ~60 s de espera máxima
  for (let i = 0; status !== 'done' && i < MAX_TRIES; i++) {
    if (status === 'failed') throw new Error('No se pudo generar el PDF. Intenta de nuevo.')
    await _sleep(2000)
    const s = await request<PdfJobRef>(`/pdfs/job/${job.job_id}/`)
    status = s.status
  }
  if (status !== 'done') {
    throw new Error('La generación del PDF está tardando demasiado. Intenta de nuevo.')
  }

  return requestBlob(`/pdfs/job/${job.job_id}/file/`, {
    headers: { Accept: 'application/pdf' },
  })
}
