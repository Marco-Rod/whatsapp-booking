import { expect, test, type Page } from '@playwright/test'

const api = 'http://localhost:8000'
const headers = {
  'access-control-allow-origin': 'http://localhost:5173',
  'access-control-allow-credentials': 'true',
}

const pendingOnboarding = {
  completed: false,
  ready: false,
  steps: { business: false, services: false, hours: false, calendar: false },
}

const completedOnboarding = {
  completed: true,
  ready: true,
  steps: { business: true, services: true, hours: true, calendar: false },
}

async function mockGoogleIdentity(page: Page) {
  await page.route('https://accounts.google.com/gsi/client', (route) =>
    route.fulfill({
      contentType: 'application/javascript',
      body: `window.google={accounts:{id:{initialize(){},renderButton(parent){const button=document.createElement('button');button.textContent='Continuar con Google';parent.append(button)}}}}`,
    }),
  )
}

async function mockOnboardingStatus(page: Page, status: object | 401) {
  await page.route(`${api}/api/v1/onboarding/status`, (route) =>
    route.fulfill({
      status: status === 401 ? 401 : 200,
      contentType: 'application/json',
      headers,
      body: JSON.stringify(
        status === 401
          ? { detail: 'Invalid business admin credentials' }
          : status,
      ),
    }),
  )
}

async function mockAuthenticatedDashboard(page: Page) {
  await page.route(`${api}/api/v1/admin/dashboard?*`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers,
      body: JSON.stringify({
        date: '2026-09-26',
        timezone: 'America/Mexico_City',
        summary: { total: 0, confirmed: 0, cancelled: 0 },
        appointments: [],
      }),
    }),
  )
  await page.route(`${api}/api/v1/admin/integrations/google`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers,
      body: JSON.stringify({
        connected: false,
        calendar_id: null,
        connected_at: null,
      }),
    }),
  )
}

test('root redirects an unauthenticated visitor to login', async ({ page }) => {
  await mockGoogleIdentity(page)
  await mockOnboardingStatus(page, 401)

  await page.goto('/')

  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByText('Continuar con Google')).toBeVisible()
})

test('root sends a pending onboarding session to onboarding', async ({ page }) => {
  await mockOnboardingStatus(page, pendingOnboarding)
  await page.route(`${api}/api/v1/onboarding/business`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers,
      body: JSON.stringify({
        name: 'Business One',
        timezone: 'America/Mexico_City',
      }),
    }),
  )

  await page.goto('/')

  await expect(page).toHaveURL(/\/onboarding$/)
  await expect(
    page.getByRole('heading', { name: 'Tu negocio', exact: true }),
  ).toBeVisible()
})

test('root renders the dashboard for a completed ready session', async ({ page }) => {
  await mockOnboardingStatus(page, completedOnboarding)
  await mockAuthenticatedDashboard(page)

  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'Citas del día.' })).toBeVisible()
})

test('login redirects an existing session without rendering Google Sign-In', async ({ page }) => {
  await mockOnboardingStatus(page, completedOnboarding)
  await mockAuthenticatedDashboard(page)

  await page.goto('/login')

  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByRole('heading', { name: 'Citas del día.' })).toBeVisible()
  await expect(page.getByText('Continuar con Google')).toHaveCount(0)
})

test('logout clears the administrative session and returning to root opens login', async ({ page }) => {
  let sessionIsActive = true
  let logoutRequested = false

  await mockGoogleIdentity(page)
  await page.route(`${api}/api/v1/onboarding/status`, (route) =>
    route.fulfill({
      status: sessionIsActive ? 200 : 401,
      contentType: 'application/json',
      headers,
      body: JSON.stringify(
        sessionIsActive
          ? completedOnboarding
          : { detail: 'Invalid business admin credentials' },
      ),
    }),
  )
  await mockAuthenticatedDashboard(page)
  await page.route(`${api}/api/v1/admin/session`, (route) => {
    logoutRequested = true
    sessionIsActive = false
    return route.fulfill({ status: 204, headers })
  })

  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Citas del día.' })).toBeVisible()

  await page.getByRole('button', { name: 'Cerrar sesión' }).click()
  await expect(page).toHaveURL(/\/login$/)
  expect(logoutRequested).toBe(true)

  await page.goto('/')
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByText('Continuar con Google')).toBeVisible()
})

test('a pending onboarding session can also log out', async ({ page }) => {
  let sessionIsActive = true

  await mockGoogleIdentity(page)
  await page.route(`${api}/api/v1/onboarding/status`, (route) =>
    route.fulfill({
      status: sessionIsActive ? 200 : 401,
      contentType: 'application/json',
      headers,
      body: JSON.stringify(
        sessionIsActive
          ? pendingOnboarding
          : { detail: 'Invalid business admin credentials' },
      ),
    }),
  )
  await page.route(`${api}/api/v1/onboarding/business`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers,
      body: JSON.stringify({
        name: 'Business One',
        timezone: 'America/Mexico_City',
      }),
    }),
  )
  await page.route(`${api}/api/v1/admin/session`, (route) => {
    sessionIsActive = false
    return route.fulfill({ status: 204, headers })
  })

  await page.goto('/')
  await expect(page).toHaveURL(/\/onboarding$/)

  await page.getByRole('button', { name: 'Cerrar sesión' }).click()
  await expect(page).toHaveURL(/\/login$/)
})
