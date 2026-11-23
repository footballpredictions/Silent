/** Browser regression: prepaid subscription can be revoked from its profile.
 * Run with Playwright available in NODE_PATH and a local admin-ui Vite server.
 * All API requests are intercepted; no real user or VPN is changed.
 */
const assert = require('node:assert/strict')
const { chromium } = require('playwright')

const now = Date.parse('2026-09-29T12:00:00Z')
const day = 86400000
const userId = '11111111-1111-4111-8111-111111111111'

async function run(browser, scenario) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(fixedNow => {
    const RealDate = Date
    window.Date = class extends RealDate {
      constructor(...args) { super(...(args.length ? args : [fixedNow])) }
      static now() { return fixedNow }
    }
    localStorage.setItem('admin_token', 'local-test-token')
  }, now)

  const subscription = {
    active: scenario.active !== false,
    plan: scenario.plan,
    started_at: '2026-09-01T12:00:00',
    expires_at: scenario.expires ?? new Date(now + scenario.days * day).toISOString().replace('Z', ''),
  }
  const user = {
    id: userId, display_id: '11111111', email: 'prepaid@example.test',
    is_verified: true, is_active: true, is_admin: !!scenario.admin,
    in_test_mode: !!scenario.test, subscription, payments_completed: 2,
  }
  const periods = [{
    id: 'subscription-1', plan_type: scenario.plan, status: 'active',
    amount_paid: 594, started_at: subscription.started_at, expires_at: subscription.expires_at,
    is_active_now: scenario.active !== false, promo_code: null,
  }]
  let revokeCount = 0
  let grantCount = 0
  let historyReads = 0
  await page.route('**/api/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    let body = {}
    let status = 200
    if (path.endsWith('/subscriptions/users')) {
      body = { items: [user], total: 1, pages: 1, page: 1 }
    } else if (path.endsWith('/subscription-history')) {
      historyReads++
      body = { user, payments: [], subscriptions: periods }
    } else if (path.endsWith('/orphan-payments')) {
      body = { items: [] }
    } else if (path.endsWith('/registration-test-mode')) {
      body = { enabled: false }
    } else if (path.endsWith('/revoke-subscription')) {
      assert.equal(request.method(), 'POST')
      assert.equal(request.headers().authorization, 'Bearer local-test-token')
      revokeCount++
      if (scenario.fail) {
        status = 400
        body = { detail: 'Не удалось снять подписку' }
      } else {
        subscription.active = false
        subscription.plan = null
        periods[0].status = 'cancelled'
        periods[0].is_active_now = false
        body = { status: 'revoked', cancelled: 1 }
      }
    } else if (path.endsWith('/grant-subscription')) {
      grantCount++
    }
    await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
  })

  try {
    await page.goto(process.env.ADMIN_UI_TEST_URL || 'http://127.0.0.1:3012/subscriptions')
    await page.getByRole('row').filter({ hasText: user.email }).getByText(user.email, { exact: true }).click()
    await page.getByText('История подписки', { exact: true }).waitFor()
    const panel = page.locator('aside').filter({ hasText: 'История подписки' })
    await panel.getByText('11111111', { exact: true }).waitFor()
    const button = panel.getByRole('button', { name: /^Снять подписку/ })
    if (scenario.hidden) {
      assert.equal(await button.count(), 0, scenario.name)
      return
    }
    await button.waitFor({ timeout: 3000 })
    assert.equal(await button.innerText(), `Снять подписку · ${Math.ceil(scenario.days)} дн.`)
    if (process.env.ADMIN_UI_TEST_SCREENSHOT && scenario.name === 'prepaid-5') {
      await page.screenshot({ path: process.env.ADMIN_UI_TEST_SCREENSHOT })
    }
    await button.click()
    if (scenario.fail) {
      await panel.getByText('Не удалось снять подписку', { exact: true }).waitFor()
      assert.equal(subscription.active, true)
      assert.equal(await button.isEnabled(), true)
    } else {
      await panel.getByText('Нет', { exact: true }).waitFor()
      assert.equal(await button.count(), 0)
      assert.ok(historyReads >= 2, 'Profile is refreshed after revoke')
      await panel.getByText('cancelled', { exact: true }).waitFor()
    }
    assert.equal(revokeCount, 1)
    assert.equal(grantCount, 0, 'Revoking must never replace prepaid time with a fixed plan')
    assert.deepEqual(errors, [])
  } finally {
    await context.close()
  }
}

async function runDeviceFilters(browser, width) {
  const page = await browser.newPage({ viewport: { width, height: 900 } })
  const requests = []
  const users = ['3', '5'].map(tier => ({
    id: tier, display_id: tier, email: `tier${tier}@example.test`,
    is_verified: true, is_active: true, is_admin: false, in_test_mode: false,
    subscription: { active: true, plan: tier === '5' ? 'monthly_5' : 'monthly' },
  }))
  await page.addInitScript(() => localStorage.setItem('admin_token', 'local-test-token'))
  await page.route('**/api/**', async route => {
    const request = route.request()
    const { pathname, searchParams } = new URL(request.url())
    const devices = searchParams.get('devices')
    const shown = users.filter(user => !devices || user.id === devices)
    let data = {}
    if (pathname.endsWith('/subscriptions/users')) {
      requests.push(Object.fromEntries(searchParams))
      data = { items: shown, total: shown.length, pages: 1 }
    } else if (pathname.endsWith('/orphan-payments')) {
      data = { items: shown.map(user => ({ user, payment: {
        id: user.id, support_code: `pending-${user.id}`, amount: 300,
        plan_type: user.subscription.plan,
      } })) }
    } else if (pathname.endsWith('/grant-subscription')) {
      assert.equal(pathname, '/api/admin/users/5/grant-subscription')
      assert.deepEqual(request.postDataJSON(), { plan_type: 'two_months_5' })
      data = { status: 'granted' }
    }
    await route.fulfill({ json: data })
  })

  try {
    await page.goto(process.env.ADMIN_UI_TEST_URL || 'http://127.0.0.1:3012/subscriptions')
    const filter = page.getByRole('combobox', { name: 'Фильтр подписок' })
    const devices = page.getByRole('combobox', { name: 'Количество устройств' })
    const rows = page.getByRole('row')
    const userRow = tier => rows.filter({ hasText: `tier${tier}@example.test` })
    await userRow(3).waitFor()
    await userRow(5).waitFor()
    assert.deepEqual(await filter.locator('option').evaluateAll(options => options.map(o => o.value)), [
      'all', 'with_sub', 'monthly', 'two_months', 'quarterly', 'granted', 'inactive', 'unpaid', 'referrals', 'trial',
    ])
    await page.getByPlaceholder('Поиск по email или ID…').fill('tier')
    for (const tier of ['3', '5']) {
      await devices.selectOption(tier)
      await filter.selectOption('monthly')
      const response = page.waitForResponse(res => {
        const params = new URL(res.url()).searchParams
        return res.url().includes('/subscriptions/users?') && params.get('filter') === 'unpaid'
          && params.get('devices') === tier && params.get('q') === 'tier'
      })
      await filter.selectOption('unpaid')
      await response
      await page.getByText(`pending-${tier}`, { exact: true }).waitFor()
      await userRow(tier).waitFor()
      assert.equal(await userRow(tier === '3' ? '5' : '3').count(), 0)
    }
    assert.ok(requests.some(query => query.devices === '5' && query.filter === 'monthly'))
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    const screenshot = process.env.ADMIN_UI_SUBSCRIPTIONS_SCREENSHOTS
    if (screenshot) await page.screenshot({ path: `${screenshot}-${width}.png` })
    await userRow(5).getByRole('button', { name: '2 месяца · 5 устр.', exact: true }).click()
    await page.getByText(/Подписка «2 месяца · 5 устр\.» выдана/).waitFor()
  } finally {
    await page.close()
  }
}

;(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true })
  try {
    const scenarios = [
      { name: 'prepaid-5', plan: 'two_months_5', days: 137.5 },
      { name: 'prepaid-3', plan: 'monthly', days: 70 },
      { name: 'less-than-day', plan: 'quarterly_5', days: 0.1 },
      { name: 'UTC-offset', plan: 'quarterly', days: 2.5, expires: '2026-10-02T03:00:00+03:00' },
      { name: 'server-error', plan: 'monthly_5', days: 42, fail: true },
      { name: 'expired', plan: 'quarterly', days: -1, active: false, hidden: true },
      { name: 'trial', plan: 'trial', days: 3, hidden: true },
      { name: 'admin', plan: 'unlimited', days: 36500, admin: true, hidden: true },
      { name: 'test', plan: 'test', days: 36500, test: true, hidden: true },
    ]
    for (const scenario of scenarios) {
      await run(browser, scenario)
      console.log(`PASS ${scenario.name}`)
    }
    for (const width of [1280, 390]) {
      await runDeviceFilters(browser, width)
      console.log(`PASS device filters and grant at ${width}px`)
    }
    console.log('OK browser scenarios; API fully mocked')
  } finally {
    await browser.close()
  }
})().catch(error => { console.error(error.message); process.exitCode = 1 })
