import { expect, test } from '@playwright/test'

const credential = 'temporary-google-id-token-that-must-stay-hidden'

async function mockGoogleIdentity(page: import('@playwright/test').Page) {
  await page.route('https://accounts.google.com/gsi/client', route => route.fulfill({
    contentType: 'application/javascript',
    body: `window.google={accounts:{id:{initialize(options){window.__gisOptions=options},renderButton(parent){const button=document.createElement('button');button.textContent='Continuar con Google';button.dataset.testid='gis-button';parent.append(button)}}}}`,
  }))
}

test('loads GIS once and renders one button under StrictMode', async ({ page }) => {
  await mockGoogleIdentity(page)
  await page.goto('/google-signin-demo')

  await expect(page.getByText('Continuar con Google')).toBeVisible()
  await expect(page.locator('#google-identity-services')).toHaveCount(1)
  await expect(page.locator('[data-testid="gis-button"]')).toHaveCount(1)
  const options = await page.evaluate(() => {
    const value = (window as typeof window & { __gisOptions?: { client_id: string; use_fedcm_for_button: boolean } }).__gisOptions
    return value && { hasClientId: Boolean(value.client_id), fedCm: value.use_fedcm_for_button }
  })
  expect(options).toEqual({ hasClientId: true, fedCm: true })
})

test('unlinked identity is rejected without exposing its credential', async ({ page }) => {
  const consoleMessages: string[] = []
  page.on('console', message => consoleMessages.push(message.text()))
  await mockGoogleIdentity(page)
  await page.route(
    'http://localhost:8000/api/v1/admin/google/session',
    route => route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Invalid Google admin authentication' }),
    }),
  )
  await page.goto('/google-signin-demo')
  await expect(page.getByText('Continuar con Google')).toBeVisible()

  await page.evaluate(value => {
    const options = (window as typeof window & { __gisOptions: { callback(response: { credential?: string }): void } }).__gisOptions
    options.callback({ credential: value })
  }, credential)

  await expect(page.getByText('Esta cuenta todavía no está vinculada.')).toBeVisible()
  await expect(page.locator('body')).not.toContainText(credential)
  expect(consoleMessages.join('\n')).not.toContain(credential)
  expect(await page.evaluate(() => ({
    local: Object.values(localStorage),
    session: Object.values(sessionStorage),
  }))).toEqual({ local: [], session: [] })
})

test('missing credential fails without exposing data', async ({ page }) => {
  await mockGoogleIdentity(page)
  await page.goto('/google-signin-demo')
  await expect(page.getByText('Continuar con Google')).toBeVisible()

  await page.evaluate(() => {
    const options = (window as typeof window & { __gisOptions: { callback(response: { credential?: string }): void } }).__gisOptions
    options.callback({})
  })

  await expect(page.getByRole('alert')).toContainText('No pudimos cargar Google Sign-In')
  await expect(page.getByText('Acceso administrativo confirmado')).toHaveCount(0)
})

test('GIS load failure leaves the application usable', async ({ page }) => {
  await page.route('https://accounts.google.com/gsi/client', route => route.abort('failed'))
  await page.goto('/google-signin-demo')

  await expect(page.getByRole('heading', { name: 'Administra tu negocio.' })).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('No pudimos cargar Google Sign-In')
})

test('missing client configuration does not load GIS', async ({ page }) => {
  let requested = false
  await page.route('https://accounts.google.com/gsi/client', route => {
    requested = true
    return route.abort()
  })

  await page.goto('/google-signin-demo/unconfigured')

  await expect(page.getByRole('alert')).toHaveText('Google Sign-In no está configurado.')
  await expect(page.locator('#google-identity-services')).toHaveCount(0)
  expect(requested).toBe(false)
})
