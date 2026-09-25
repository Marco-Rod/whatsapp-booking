import type {
  GoogleCalendarDisconnectResult,
  GoogleCalendarIntegration,
} from '../types/googleIntegration'

function getApiBaseUrl(): string {
  const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '')

  if (base === undefined) {
    throw new Error('Falta configurar la dirección de la API.')
  }

  return base
}

function getGoogleIntegrationUrl(businessId: number): string {
  return `${getApiBaseUrl()}/api/v1/businesses/${businessId}/integrations/google`
}

export async function getGoogleCalendarIntegration(
  businessId: number,
  signal?: AbortSignal,
): Promise<GoogleCalendarIntegration> {
  const response = await fetch(getGoogleIntegrationUrl(businessId), {
    signal,
  })

  if (!response.ok) {
    throw new Error(
      response.status === 404
        ? 'No encontramos este negocio.'
        : 'No pudimos consultar Google Calendar. Intenta de nuevo en un momento.',
    )
  }

  return response.json() as Promise<GoogleCalendarIntegration>
}

export function getGoogleCalendarConnectUrl(businessId: number): string {
  return `${getGoogleIntegrationUrl(businessId)}/connect`
}

export function connectGoogleCalendar(businessId: number): void {
  window.location.href = getGoogleCalendarConnectUrl(businessId)
}

export async function disconnectGoogleCalendar(
  businessId: number,
  signal?: AbortSignal,
): Promise<GoogleCalendarDisconnectResult> {
  const response = await fetch(getGoogleIntegrationUrl(businessId), {
    method: 'DELETE',
    signal,
  })

  if (!response.ok) {
    throw new Error(
      response.status === 404
        ? 'No encontramos este negocio.'
        : 'No pudimos desconectar Google Calendar. Intenta de nuevo en un momento.',
    )
  }

  return response.json() as Promise<GoogleCalendarDisconnectResult>
}
