import { expect, test, type Page } from '@playwright/test'
import type { DashboardResponse } from '../src/types/dashboard'

const api = process.env.DASHBOARD_API_URL || 'http://localhost:8000'
const date = process.env.DASHBOARD_TEST_DATE || '2026-09-17'
const cancelledDate = process.env.DASHBOARD_CANCELLED_DATE || '2026-09-18'
const initialDate = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'America/Mexico_City',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
}).format(new Date())
const responseHeaders = {
  'access-control-allow-origin': 'http://localhost:5173',
  'access-control-allow-credentials': 'true',
}

async function mockGoogleCalendarIntegration(page: Page) {
  await page.route(`${api}/api/v1/admin/integrations/google`, route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: responseHeaders,
      body: JSON.stringify({
        connected: false,
        calendar_id: null,
        connected_at: null,
      }),
    }),
  )
}

async function mockCompletedSession(page: Page) {
  await page.route(`${api}/api/v1/onboarding/status`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: responseHeaders,
      body: JSON.stringify({
        completed: true,
        ready: true,
        steps: {
          business: true,
          services: true,
          hours: true,
          calendar: false,
        },
      }),
    }),
  )
}

async function mockAdminDashboard(
  page: Page,
  fixtures: Map<string, DashboardResponse>,
) {
  await page.route(`${api}/api/v1/admin/dashboard?*`, route => {
    const requestedDate = new URL(route.request().url()).searchParams.get('date')
    const data = requestedDate ? fixtures.get(requestedDate) : undefined

    return route.fulfill({
      status: data ? 200 : 404,
      contentType: 'application/json',
      headers: responseHeaders,
      body: JSON.stringify(data ?? { detail: 'No encontramos este negocio.' }),
    })
  })
}

for (const [name, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844]] as const) {
  test(`${name}: real appointments, dates, statuses and screenshot`, async ({ page, request }) => {
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    page.on('console', message => {
      if (
        message.type() === 'error' &&
        !message.text().includes('ERR_NETWORK_ACCESS_DENIED')
      ) {
        errors.push(message.text())
      }
    })
    await page.setViewportSize({ width, height })
    await mockCompletedSession(page)
    await mockGoogleCalendarIntegration(page)
    const nextDate = new Date(`${cancelledDate}T12:00:00Z`)
    nextDate.setUTCDate(nextDate.getUTCDate() + 1)
    const fixtureDates = [
      initialDate,
      date,
      cancelledDate,
      nextDate.toISOString().slice(0, 10),
      '2040-01-01',
    ]
    const fixtures = new Map<string, DashboardResponse>()
    for (const fixtureDate of fixtureDates) {
      const response = await request.get(
        `${api}/api/v1/businesses/1/dashboard?date=${fixtureDate}`,
      )
      expect(response.ok()).toBeTruthy()
      fixtures.set(fixtureDate, await response.json())
    }
    await mockAdminDashboard(page, fixtures)
    const data = fixtures.get(date)!
    expect(data.appointments.length).toBeGreaterThan(0)
    await page.goto('/')
    await page.getByLabel('Fecha de la agenda').fill(date)
    await expect(page.getByTestId('appointment')).toHaveCount(data.appointments.length)
    for (const [index, appointment] of data.appointments.entries()) {
      const row = page.getByTestId('appointment').nth(index)
      await expect(row).toContainText(appointment.service.name)
      await expect(row).toContainText(appointment.customer?.name || 'Sin nombre')
      await expect(row).toContainText(appointment.status === 'CONFIRMED' ? 'Confirmada' : 'Cancelada')
      await expect(row).toContainText(appointment.calendar_synced ? 'Calendar vinculado' : 'Sin vincular a Calendar')
      await expect(row).toContainText(appointment.reminder_sent ? 'Recordatorio enviado' : 'Recordatorio pendiente')
      const local = new Intl.DateTimeFormat('es-MX', { timeZone: data.timezone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(appointment.starts_at))
      await expect(row.locator('time')).toHaveText(local)
    }
    await expect(page.locator('.summary-card.total strong')).toHaveText(String(data.summary.total))
    await expect(page.locator('.summary-card.confirmed strong')).toHaveText(String(data.summary.confirmed))
    await expect(page.locator('.summary-card.cancelled strong')).toHaveText(String(data.summary.cancelled))
    expect(await page.locator('body').innerText()).not.toMatch(/\+?52\d{10}/)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
    await page.evaluate(() => document.fonts.ready)
    await page.getByRole('heading', { name: 'Citas del día.' }).click()
    await page.screenshot({ path: `../docs/screenshots/dashboard-${name}.png`, fullPage: true })
    await page.getByLabel('Fecha de la agenda').fill(cancelledDate)
    await expect(page.locator('.badge.cancelled')).toBeVisible()
    await expect(page.getByTestId('appointment')).toContainText('Calendar vinculado')
    await expect(page.getByTestId('appointment')).toContainText('Recordatorio pendiente')
    await page.getByRole('button', { name: 'Día siguiente' }).click()
    await expect(page.getByLabel('Fecha de la agenda')).toHaveValue(nextDate.toISOString().slice(0, 10))
    await page.getByLabel('Fecha de la agenda').fill('2040-01-01')
    await expect(page.getByText('No tienes citas para este día')).toBeVisible()
    await expect(page.locator('.summary-card.total strong')).toHaveText('0')
    expect(errors).toEqual([])
  })
}

test('loading, network error and retry with administrative dashboard recovery', async ({ page }) => {
  let fail = true
  await mockCompletedSession(page)
  await mockGoogleCalendarIntegration(page)
  await page.route(`${api}/api/v1/admin/dashboard?*`, async route => {
    if (fail) {
      await new Promise(resolve => setTimeout(resolve, 500))
      await route.abort('failed')
    } else await route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: responseHeaders,
      body: JSON.stringify({
        date: '2026-09-26',
        timezone: 'America/Mexico_City',
        summary: { total: 0, confirmed: 0, cancelled: 0 },
        appointments: [],
      }),
    })
  })
  await page.goto('/')
  await expect(
    page.getByRole('status').filter({ hasText: 'Cargando agenda' }),
  ).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('No pudimos cargar tu agenda')
  fail = false
  await page.getByRole('button', { name: 'Reintentar' }).click()
  await expect(page.getByRole('heading', { name: /Tu agenda/ })).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})
