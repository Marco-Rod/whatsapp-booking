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

export async function completeOnboarding(): Promise<OnboardingStatus> {
  const response = await fetch(
    `${getApiBaseUrl()}/api/v1/onboarding/complete`,
    {
      method: 'POST',
      credentials: 'include',
    },
  )
  if (!response.ok) throw new AdminAuthError(response.status)
  return response.json() as Promise<OnboardingStatus>
}

export interface OnboardingBusinessConfiguration {
  name: string
  timezone: string
}

export async function getOnboardingBusiness(): Promise<OnboardingBusinessConfiguration> {
  const response = await fetch(
    `${getApiBaseUrl()}/api/v1/onboarding/business`,
    { credentials: 'include' },
  )
  if (!response.ok) throw new AdminAuthError(response.status)
  return response.json() as Promise<OnboardingBusinessConfiguration>
}

export interface OnboardingServiceConfiguration {
  name: string
  duration_minutes: number
}

export interface OnboardingServicesConfiguration {
  services: OnboardingServiceConfiguration[]
}

export async function getOnboardingServices(): Promise<OnboardingServicesConfiguration> {
  const response = await fetch(
    `${getApiBaseUrl()}/api/v1/onboarding/services`,
    { credentials: 'include' },
  )
  if (!response.ok) throw new AdminAuthError(response.status)
  return response.json() as Promise<OnboardingServicesConfiguration>
}

export interface OnboardingBusinessHourConfiguration {
  day_of_week: number
  is_open: boolean
  open_time: string | null
  close_time: string | null
}

export interface OnboardingHoursConfiguration {
  hours: OnboardingBusinessHourConfiguration[]
}

export async function getOnboardingHours(): Promise<OnboardingHoursConfiguration> {
  const response = await fetch(
    `${getApiBaseUrl()}/api/v1/onboarding/hours`,
    { credentials: 'include' },
  )
  if (!response.ok) throw new AdminAuthError(response.status)
  return response.json() as Promise<OnboardingHoursConfiguration>
}

export interface UpdateHoursOnboardingInput {
  hours: OnboardingBusinessHourConfiguration[]
}

export async function updateOnboardingHours(
  input: UpdateHoursOnboardingInput,
): Promise<OnboardingStatus> {
  const response = await fetch(
    `${getApiBaseUrl()}/api/v1/onboarding/hours`,
    {
      method: 'PUT',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        hours: input.hours.map((hour) => ({
          weekday: hour.day_of_week,
          is_closed: !hour.is_open,
          start_time: hour.open_time,
          end_time: hour.close_time,
        })),
      }),
    },
  )
  if (!response.ok) throw new AdminAuthError(response.status)
  return response.json() as Promise<OnboardingStatus>
}

export interface UpdateServicesOnboardingInput {
  services: OnboardingServiceConfiguration[]
}

export async function updateOnboardingServices(
  input: UpdateServicesOnboardingInput,
): Promise<OnboardingStatus> {
  const response = await fetch(
    `${getApiBaseUrl()}/api/v1/onboarding/services`,
    {
      method: 'PUT',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    },
  )
  if (!response.ok) throw new AdminAuthError(response.status)
  return response.json() as Promise<OnboardingStatus>
}

export interface UpdateBusinessOnboardingInput {
  name: string
  timezone: string
}

export async function updateOnboardingBusiness(
  input: UpdateBusinessOnboardingInput,
): Promise<OnboardingStatus> {
  const response = await fetch(
    `${getApiBaseUrl()}/api/v1/onboarding/business`,
    {
      method: 'PUT',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    },
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
