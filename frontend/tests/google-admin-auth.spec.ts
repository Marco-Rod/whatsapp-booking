import { expect, test, type Page, type Route } from '@playwright/test'

const credential = 'realistic-temporary-google-credential'
const activationKey = 'one-time-activation-key'
const origin = 'http://localhost:5173'

async function mockGoogleIdentity(page: Page) {
  await page.route('https://accounts.google.com/gsi/client', route => route.fulfill({
    contentType: 'application/javascript',
    body: `window.google={accounts:{id:{initialize(options){window.__gisOptions=options},renderButton(parent){const button=document.createElement('button');button.textContent='Continuar con Google';parent.append(button)}}}}`,
  }))
}

async function sendGoogleCredential(page: Page) {
  await page.evaluate(value => {
    const options = (window as typeof window & { __gisOptions: { callback(response: { credential: string }): void } }).__gisOptions
    options.callback({ credential: value })
  }, credential)
}

function cors(route: Route) {
  return route.fulfill({
    status: 200,
    headers: {
      'access-control-allow-origin': origin,
      'access-control-allow-credentials': 'true',
      'access-control-allow-methods': 'GET,POST,DELETE',
      'access-control-allow-headers': 'authorization,content-type',
    },
  })
}

function responseHeaders() {
  return {
    'access-control-allow-origin': origin,
    'access-control-allow-credentials': 'true',
  }
}

const onboarding = {
  completed: false,
  ready: true,
  steps: { business: true, services: true, hours: true, calendar: false },
}

test('initial activation sends Bearer only to link and uses the HttpOnly cookie', async ({ page, context }) => {
  const requests: Array<{ url: string; method: string; authorization?: string; body?: string | null; cookie?: string }> = []
  let sessionActive = false
  await mockGoogleIdentity(page)
  await page.route('http://localhost:8000/**', async route => {
    const request = route.request()
    if (request.method() === 'OPTIONS') return cors(route)
    requests.push({
      url: request.url(),
      method: request.method(),
      authorization: request.headers().authorization,
      body: request.postData(),
      cookie: request.headers().cookie,
    })
    if (request.url().endsWith('/admin/google/link')) {
      sessionActive = true
      await context.addCookies([
        {
          name: 'admin_session',
          value: 'signed-session',
          url: 'http://localhost:8000',
          httpOnly: true,
          sameSite: 'Lax',
        },
      ])

      return route.fulfill({
        status: 204,
        headers: responseHeaders(),
      })
    }
    if (request.url().endsWith('/onboarding/status') && !sessionActive) {
      return route.fulfill({
        status: 401,
        headers: responseHeaders(),
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Invalid business admin credentials' }),
      })
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: responseHeaders(),
      body: JSON.stringify(onboarding),
    })
  })
  await page.goto('/login')
  await page.getByRole('button', { name: /Activar mi negocio/ }).click()
  const key = page.getByLabel('Clave de activación')
  await expect(key).toHaveAttribute('type', 'password')
  await key.fill(activationKey)
  await expect(page.getByText('Continuar con Google')).toBeVisible()

  await sendGoogleCredential(page)

  await expect(page).toHaveURL(/\/onboarding$/)
  const link = requests.find(request => request.url.endsWith('/admin/google/link'))
  const status = requests.find(request =>
    request.url.endsWith('/onboarding/status') &&
    request.cookie?.includes('admin_session=signed-session'),
  )
  expect(link?.authorization).toBe(`Bearer ${activationKey}`)
  expect(link?.body).toBe(JSON.stringify({ credential }))
  expect(status?.authorization).toBeUndefined()
  expect(status?.cookie).toContain('admin_session=signed-session')
  expect(await page.evaluate(() => ({ local: Object.values(localStorage), session: Object.values(sessionStorage) }))).toEqual({ local: [], session: [] })
  await expect(page.locator('body')).not.toContainText(credential)
  await expect(page.locator('body')).not.toContainText(activationKey)
})

test('daily Google login sends no Bearer and obtains onboarding status', async ({ page }) => {
  const authorizations: Array<string | undefined> = []
  let sessionActive = false
  await mockGoogleIdentity(page)
  await page.route('http://localhost:8000/**', route => {
    const request = route.request()
    if (request.method() === 'OPTIONS') return cors(route)
    authorizations.push(request.headers().authorization)
    if (request.url().endsWith('/admin/google/session')) {
      sessionActive = true
      return route.fulfill({
        status: 204,
        headers: {
          ...responseHeaders(),
          'set-cookie': 'admin_session=signed-session; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800',
        },
      })
    }
    if (request.url().endsWith('/onboarding/status') && !sessionActive) {
      return route.fulfill({
        status: 401,
        headers: responseHeaders(),
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Invalid business admin credentials' }),
      })
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: responseHeaders(),
      body: JSON.stringify(onboarding),
    })
  })
  await page.goto('/login')
  await expect(page.getByText('Continuar con Google')).toBeVisible()

  await sendGoogleCredential(page)

  await expect(page).toHaveURL(/\/onboarding$/)
  expect(authorizations.every(value => value === undefined)).toBeTruthy()
})

test('completed onboarding redirects daily Google login to the dashboard', async ({ page }) => {
  const completedOnboarding = {
    ...onboarding,
    completed: true,
  }
  let sessionActive = false
  await mockGoogleIdentity(page)
  await page.route('http://localhost:8000/**', route => {
    const request = route.request()
    if (request.method() === 'OPTIONS') return cors(route)
    if (request.url().endsWith('/admin/google/session')) {
      sessionActive = true
      return route.fulfill({ status: 204, headers: { ...responseHeaders(), 'set-cookie': 'admin_session=signed-session; Path=/; HttpOnly; SameSite=Lax' } })
    }
    if (request.url().endsWith('/onboarding/status') && !sessionActive) {
      return route.fulfill({
        status: 401,
        headers: responseHeaders(),
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Invalid business admin credentials' }),
      })
    }
    return route.fulfill({ status: 200, headers: responseHeaders(), contentType: 'application/json', body: JSON.stringify(completedOnboarding) })
  })
  await page.goto('/login')
  await expect(page.getByText('Continuar con Google')).toBeVisible()
  await sendGoogleCredential(page)

  await expect(page).toHaveURL(/\/$/)
})
