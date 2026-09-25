import { expect, test } from '@playwright/test'
import type { DashboardResponse } from '../src/types/dashboard'

const api = process.env.DASHBOARD_API_URL || 'http://localhost:8000'
const date = process.env.DASHBOARD_TEST_DATE || '2026-09-17'
const cancelledDate = process.env.DASHBOARD_CANCELLED_DATE || '2026-09-18'

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
    const response = await request.get(`${api}/api/v1/businesses/1/dashboard?date=${date}`)
    expect(response.ok()).toBeTruthy()
    const data: DashboardResponse = await response.json()
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
    const nextDate = new Date(`${cancelledDate}T12:00:00Z`)
    nextDate.setUTCDate(nextDate.getUTCDate() + 1)
    await expect(page.getByLabel('Fecha de la agenda')).toHaveValue(nextDate.toISOString().slice(0, 10))
    await page.getByLabel('Fecha de la agenda').fill('2040-01-01')
    await expect(page.getByText('No tienes citas para este día')).toBeVisible()
    await expect(page.locator('.summary-card.total strong')).toHaveText('0')
    expect(errors).toEqual([])
  })
}

test('loading, network error and retry with real API recovery', async ({ page }) => {
  let fail = true
  await page.route('**/dashboard?*', async route => {
    if (fail) {
      await new Promise(resolve => setTimeout(resolve, 500))
      await route.abort('failed')
    } else await route.continue()
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
