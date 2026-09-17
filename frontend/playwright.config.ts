import { defineConfig } from '@playwright/test'

// Read-only checks against the running frontend and real, seeded backend.
export default defineConfig({
  testDir: './tests',
  workers: 1,
  use: { baseURL: process.env.DASHBOARD_UI_URL || 'http://127.0.0.1:5173', browserName: 'chromium' },
})
