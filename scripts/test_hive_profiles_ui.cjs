/** Profiles are available on every node; pending changes never pretend to be applied. */
const assert = require('node:assert/strict')
const { chromium } = require('../admin-ui/node_modules/playwright')

;(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1366, height: 900 } })
    const errors = []
    const changes = []
    let failure = null
    const cells = ['Улей', 'Сота 1', 'Сота 2', 'Сота 3'].map((name, i) => ({
      id: `node-${i}`, name, is_queen: i === 0, public_ip: `198.51.100.${i + 1}`,
      wdtt_port: 56000, status: 'active', max_online: 100, online_count: 2,
      assigned_devices: 3, has_ssh_password: i !== 0, ai_exit: i === 3,
      profiles: { ai: i === 3, gaming: i === 2, wg_mtu: i === 2 ? 1420 : 1200,
        revision: 0, state: 'ready', error: null },
    }))
    page.on('pageerror', error => errors.push(error.message))
    page.on('dialog', dialog => dialog.accept())
    await page.addInitScript(() => localStorage.setItem('admin_token', 'fixture-token'))
    await page.route('**/api/admin/**', async route => {
      const url = new URL(route.request().url())
      let body = {}
      if (url.pathname === '/api/admin/sessions') body = { sessions: [] }
      else if (url.pathname === '/api/admin/hive/cells') body = cells
      else if (url.pathname.endsWith('/profiles')) {
        if (failure === 'offline') return route.abort('failed')
        if (failure === 'conflict') return route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: 'Настройки уже изменены. Обновите страницу и повторите' }) })
        changes.push(route.request().postDataJSON())
        cells[0].profiles = { ...cells[0].profiles, state: 'running', requested: { ai: true, gaming: false } }
        body = { message: 'Настройка профилей запущена' }
      }
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
    })
    await page.goto(process.env.HIVE_UI_URL || 'http://127.0.0.1:3012/hive')
    const queen = page.getByRole('article', { name: 'Улей', exact: true })
    await queen.waitFor()
    for (const name of ['Улей', 'Сота 1', 'Сота 2', 'Сота 3']) {
      const card = page.getByRole('article', { name, exact: true })
      assert.equal(await card.getByRole('button', { name: /профиль для ИИ/i }).count(), 1, `${name}: AI control`)
      assert.equal(await card.getByRole('button', { name: /игровой профиль/i }).count(), 1, `${name}: gaming control`)
    }
    await queen.getByRole('button', { name: 'Профиль для ИИ', exact: true }).click()
    await queen.getByText('Настройка профилей…', { exact: true }).waitFor()
    assert.equal(changes[0].ai, true)
    assert.equal(changes[0].expected_revision, 0)
    assert(await queen.getByRole('button', { name: 'Профиль для ИИ', exact: true }).isDisabled())
    assert.equal(await queen.getByText('Для ИИ', { exact: true }).count(), 0, 'pending is not applied')
    for (const [width, name] of [[1366, 'desktop'], [390, 'mobile']]) {
      await page.setViewportSize({ width, height: 900 })
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `${name}: overflow`)
      if (process.env.HIVE_UI_SCREENSHOTS) await page.screenshot({ path: `${process.env.HIVE_UI_SCREENSHOTS}/hive-profiles-${name}.png`, fullPage: true })
    }
    cells[0].profiles = { ...cells[0].profiles, state: 'error', rolled_back: true, error: 'Проверка сервера не прошла' }
    await page.reload()
    await queen.getByRole('alert').filter({ hasText: 'Профиль не переключён' }).waitFor()
    assert(await queen.getByRole('button', { name: 'Профиль для ИИ', exact: true }).isEnabled())
    failure = 'conflict'
    await queen.getByRole('button', { name: 'Профиль для ИИ', exact: true }).click()
    await page.getByText('Настройки уже изменены. Обновите страницу и повторите', { exact: true }).waitFor()
    failure = 'offline'
    await queen.getByRole('button', { name: 'Профиль для ИИ', exact: true }).click()
    await page.getByText('Не удалось получить результат. Обновите страницу, чтобы проверить состояние профилей.', { exact: true }).waitFor()
    assert.deepEqual(errors, [])
    console.log('ok: all nodes, queen without SSH, revision, pending/rollback/conflict/offline states, desktop/mobile')
  } finally { await browser.close() }
})().catch(error => { console.error(error); process.exitCode = 1 })
