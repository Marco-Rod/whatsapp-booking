import type {
  GoogleCalendarDisconnectResult,
  GoogleCalendarIntegration,
} from '../types/googleIntegration'
import { AdminAuthError } from './adminAuth'

function getApiBaseUrl(): string {
  const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '')

  if (base === undefined) {
    throw new Error('Falta configurar la dirección de la API.')
  }

  return base
}

function getGoogleIntegrationUrl(): string {
  return `${getApiBaseUrl()}/api/v1/admin/integrations/google`
}

export async function getGoogleCalendarIntegration(
  signal?: AbortSignal,
): Promise<GoogleCalendarIntegration> {
  const response = await fetch(getGoogleIntegrationUrl(), {
    credentials: 'include',
    signal,
  })

  if (!response.ok) {
    if (response.status === 401) throw new AdminAuthError(response.status)
    throw new Error(
      response.status === 404
        ? 'No encontramos este negocio.'
        : 'No pudimos consultar Google Calendar. Intenta de nuevo en un momento.',
    )
  }

  return response.json() as Promise<GoogleCalendarIntegration>
}

export function getGoogleCalendarConnectUrl(
  returnTo: 'dashboard' | 'onboarding' = 'dashboard',
): string {
  return `${getGoogleIntegrationUrl()}/connect?return_to=${returnTo}`
}

export function connectGoogleCalendar(
  returnTo: 'dashboard' | 'onboarding' = 'dashboard',
): void {
  window.location.href = getGoogleCalendarConnectUrl(returnTo)
}

export async function disconnectGoogleCalendar(
  signal?: AbortSignal,
): Promise<GoogleCalendarDisconnectResult> {
  const response = await fetch(getGoogleIntegrationUrl(), {
    method: 'DELETE',
    credentials: 'include',
    signal,
  })

  if (!response.ok) {
    if (response.status === 401) throw new AdminAuthError(response.status)
    throw new Error(
      response.status === 404
        ? 'No encontramos este negocio.'
        : 'No pudimos desconectar Google Calendar. Intenta de nuevo en un momento.',
    )
  }

  return response.json() as Promise<GoogleCalendarDisconnectResult>
}
