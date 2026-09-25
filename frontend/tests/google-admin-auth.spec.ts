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
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: responseHeaders(),
      body: JSON.stringify(onboarding),
    })
  })
  await page.goto('/google-signin-demo')
  await page.getByRole('button', { name: /Activar mi negocio/ }).click()
  const key = page.getByLabel('Clave de activación')
  await expect(key).toHaveAttribute('type', 'password')
  await key.fill(activationKey)
  await expect(page.getByText('Continuar con Google')).toBeVisible()

  await sendGoogleCredential(page)

  await expect(page.getByText('✓ Acceso administrativo confirmado')).toBeVisible()
  await expect(page.getByText('Tu cuenta Google quedó vinculada correctamente.')).toBeVisible()
  await expect(page.getByLabel('Clave de activación')).toHaveCount(0)
  const link = requests.find(request => request.url.endsWith('/admin/google/link'))
  const status = requests.find(request => request.url.endsWith('/onboarding/status'))
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
  await mockGoogleIdentity(page)
  await page.route('http://localhost:8000/**', route => {
    const request = route.request()
    if (request.method() === 'OPTIONS') return cors(route)
    authorizations.push(request.headers().authorization)
    if (request.url().endsWith('/admin/google/session')) return route.fulfill({
      status: 204,
      headers: {
        ...responseHeaders(),
        'set-cookie': 'admin_session=signed-session; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800',
      },
    })
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: responseHeaders(),
      body: JSON.stringify(onboarding),
    })
  })
  await page.goto('/google-signin-demo')
  await expect(page.getByText('Continuar con Google')).toBeVisible()

  await sendGoogleCredential(page)

  await expect(page.getByText('Sesión iniciada correctamente.')).toBeVisible()
  await expect(page.getByText('✓ Acceso administrativo confirmado')).toBeVisible()
  expect(authorizations).toEqual([undefined, undefined])
})

test('logout removes the authenticated UI', async ({ page }) => {
  await mockGoogleIdentity(page)
  await page.route('http://localhost:8000/**', route => {
    const request = route.request()
    if (request.method() === 'OPTIONS') return cors(route)
    if (request.method() === 'DELETE') return route.fulfill({ status: 200, headers: responseHeaders(), contentType: 'application/json', body: '{"authenticated":false}' })
    if (request.url().endsWith('/admin/google/session')) return route.fulfill({ status: 204, headers: { ...responseHeaders(), 'set-cookie': 'admin_session=signed-session; Path=/; HttpOnly; SameSite=Lax' } })
    return route.fulfill({ status: 200, headers: responseHeaders(), contentType: 'application/json', body: JSON.stringify(onboarding) })
  })
  await page.goto('/google-signin-demo')
  await sendGoogleCredential(page)
  await expect(page.getByText('✓ Acceso administrativo confirmado')).toBeVisible()

  await page.getByRole('button', { name: 'Cerrar sesión' }).click()

  await expect(page.getByText('Sesión cerrada.')).toBeVisible()
  await expect(page.getByText('✓ Acceso administrativo confirmado')).toHaveCount(0)
  await expect(page.getByText('Continuar con Google')).toBeVisible()
})
