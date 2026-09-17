import type { DashboardResponse } from '../types/dashboard'

export async function getDashboard(businessId: number, date: string, signal: AbortSignal): Promise<DashboardResponse> {
  const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '')
  if (base === undefined) throw new Error('Falta configurar la dirección de la API.')
  const response = await fetch(`${base}/api/v1/businesses/${businessId}/dashboard?${new URLSearchParams({ date })}`, { signal })
  if (!response.ok) throw new Error(response.status === 404
    ? 'No encontramos este negocio.' : 'No pudimos cargar la agenda. Intenta de nuevo en un momento.')
  return response.json() as Promise<DashboardResponse>
}
