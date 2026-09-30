/** Browser regression for the Users table device limit and manual override.
 * Run with Playwright in NODE_PATH and a local admin-ui Vite server on port 3012.
 * Every API call is mocked; this never changes a real subscription or VPN session.
 */
const assert = require('node:assert/strict')
const { chromium } = require('playwright')

const id = '11111111-1111-4111-8111-111111111111'

;(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true })
  try {
    const page = await browser.newPage()
    const errors = []
    const writes = []
    let deviceReads = 0
    let failNextWrite = true
    const user = {
      id, display_id: '11111111', email: 'five@example.test',
      is_verified: true, is_active: true, is_admin: false,
      created_at: '2026-09-01T00:00:00Z', bootstrap_hash: null,
      server_hashes: 0, devices_count: 2,
      subscription: { active: true, plan: 'monthly_5', expires_at: '2026-11-01T00:00:00Z' },
      max_devices: 5, device_limit_override: null,
    }
    page.on('pageerror', error => errors.push(error.message))
    await page.addInitScript(() => localStorage.setItem('admin_token', 'local-test-token'))
    await page.route('**/api/admin/**', async route => {
      const request = route.request()
      const path = new URL(request.url()).pathname
      if (path === '/api/admin/sessions') {
        return route.fulfill({ contentType: 'application/json', body: '{"sessions":[]}' })
      }
      if (path === '/api/admin/users/paged' && request.method() === 'GET') {
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify({
          items: [user], total: 1, matched: 1, page: 1, page_size: 50,
        }) })
      }
      if (path === `/api/admin/users/${id}/device-limit` && request.method() === 'PUT') {
        const body = request.postDataJSON()
        writes.push(body)
        if (failNextWrite) {
          failNextWrite = false
          return route.fulfill({ status: 400, contentType: 'application/json', body: '{"detail":"Лимит не сохранён"}' })
        }
        user.device_limit_override = body.max_devices
        user.max_devices = body.max_devices ?? 5
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify({
          max_devices: user.max_devices, device_limit_override: user.device_limit_override,
        }) })
      }
      if (path === `/api/admin/users/${id}/devices`) deviceReads++
      return route.fulfill({ status: 404, contentType: 'application/json', body: '{}' })
    })

    await page.goto('http://127.0.0.1:3012/users')
    const row = page.getByRole('row').filter({ hasText: user.email })
    const limitButton = row.getByRole('button', { name: /2 из 5 устройств/ })
    try { await limitButton.waitFor({ timeout: 3000 }) }
    catch (error) { console.error((await page.locator('body').innerText()).slice(0, 1000)); throw error }
    await row.getByText('Месяц · 5 устройств').waitFor({ timeout: 3000 })
    await limitButton.click()
    if (process.env.ADMIN_UI_TEST_SCREENSHOT) {
      await page.screenshot({ path: process.env.ADMIN_UI_TEST_SCREENSHOT })
    }
    await page.getByRole('button', { name: 'Установить 3 устройства' }).click()
    await page.getByRole('alert').getByText('Лимит не сохранён').waitFor()
    await row.getByRole('button', { name: /2 из 5 устройств/ }).waitFor()
    await page.getByRole('button', { name: 'Установить 3 устройства' }).click()
    await row.getByRole('button', { name: /2 из 3 устройств/ }).waitFor()
    assert.deepEqual(writes, [{ max_devices: 3 }, { max_devices: 3 }])
    assert.equal(user.subscription.plan, 'monthly_5')
    assert.equal(user.subscription.expires_at, '2026-11-01T00:00:00Z')
    await row.getByText('вручную').waitFor()
    await row.getByRole('button', { name: /2 из 3 устройств/ }).click()
    await page.getByRole('button', { name: 'По тарифу (5 устройств)' }).click()
    await row.getByRole('button', { name: /2 из 5 устройств/ }).waitFor()
    assert.deepEqual(writes, [{ max_devices: 3 }, { max_devices: 3 }, { max_devices: null }])
    assert.equal(deviceReads, 0, 'Clicking the limit must not open the sessions panel')
    assert.deepEqual(errors, [])
    console.log('ok: paid 5-device plan, manual 3-device override, reset to plan')
    await page.close()
  } finally {
    await browser.close()
  }
})().catch(error => { console.error(error.message); process.exitCode = 1 })
