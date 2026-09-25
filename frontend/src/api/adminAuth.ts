import type { OnboardingStatus } from '../types/onboarding'

export class AdminAuthError extends Error {
  constructor(public readonly status: number) {
    super('Google admin authentication failed')
    this.name = 'AdminAuthError'
  }
}

function getApiBaseUrl(): string {
  const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '')
  if (base === undefined) {
    throw new Error('Falta configurar la dirección de la API.')
  }
  return base
}

async function googleAdminRequest(
  path: 'link' | 'session',
  credential: string,
  adminToken?: string,
): Promise<void> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  if (path === 'link' && adminToken) {
    headers.Authorization = `Bearer ${adminToken}`
  }

  const response = await fetch(
    `${getApiBaseUrl()}/api/v1/admin/google/${path}`,
    {
      method: 'POST',
      credentials: 'include',
      headers,
      body: JSON.stringify({ credential }),
    },
  )
  if (!response.ok) throw new AdminAuthError(response.status)
}

export function loginWithGoogle(credential: string): Promise<void> {
  return googleAdminRequest('session', credential)
}

export function linkGoogleAdmin(
  credential: string,
  adminToken: string,
): Promise<void> {
  return googleAdminRequest('link', credential, adminToken)
}

export async function getOnboardingStatus(): Promise<OnboardingStatus> {
  const response = await fetch(
    `${getApiBaseUrl()}/api/v1/onboarding/status`,
    { credentials: 'include' },
  )
  if (!response.ok) throw new AdminAuthError(response.status)
  return response.json() as Promise<OnboardingStatus>
}

export async function logoutAdmin(): Promise<void> {
  const response = await fetch(
    `${getApiBaseUrl()}/api/v1/admin/session`,
    { method: 'DELETE', credentials: 'include' },
  )
  if (!response.ok) throw new AdminAuthError(response.status)
}
