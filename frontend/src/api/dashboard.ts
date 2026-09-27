import type { DashboardResponse } from '../types/dashboard'
import { AdminAuthError } from './adminAuth'

export async function getDashboard(
  date: string,
  signal: AbortSignal,
): Promise<DashboardResponse> {
  const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '')
  if (base === undefined) throw new Error('Falta configurar la dirección de la API.')
  const response = await fetch(
    `${base}/api/v1/admin/dashboard?${new URLSearchParams({ date })}`,
    { credentials: 'include', signal },
  )
  if (response.status === 401) throw new AdminAuthError(response.status)
  if (!response.ok) throw new Error(response.status === 404
    ? 'No encontramos este negocio.' : 'No pudimos cargar la agenda. Intenta de nuevo en un momento.')
  return response.json() as Promise<DashboardResponse>
}
