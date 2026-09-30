/** Browser regression: dashboard paints before heavy details; Users fetches one page. */
const assert = require('node:assert/strict')
const { chromium } = require('playwright')

const base = {
  system: { node_id: 'queen', cpu_percent: 1, memory_total_gb: 8,
    memory_used_gb: 1, memory_percent: 12, reachable: true },
  users: { total: 1200, active_subscriptions: 5, connected_devices: null,
    peak_online_devices: 10 },
  resource_nodes: [{ id: 'queen', name: 'Улей', title: 'Улей', is_queen: true }],
}
const user = (id, email) => ({
  id, display_id: id, email, is_verified: true, is_active: true, is_admin: false,
  created_at: '2026-09-01T00:00:00Z', bootstrap_hash: null, server_hashes: 0,
  devices_count: 1, max_devices: 3, subscription: { active: false, plan: null, expires_at: null },
})

;(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true })
  try {
    const page = await browser.newPage()
    const errors = []
    const userRequests = []
    let compactFullRequests = 0
    let releaseFull
    const fullGate = new Promise(resolve => { releaseFull = resolve })
    page.on('pageerror', error => errors.push(error.message))
    await page.addInitScript(() => localStorage.setItem('admin_token', 'local-test-token'))
    await page.route('**/api/admin/**', async route => {
      const url = new URL(route.request().url())
      if (url.pathname === '/api/admin/sessions') {
        return route.fulfill({ contentType: 'application/json', body: '{"sessions":[]}' })
      }
      if (url.pathname === '/api/admin/stats') {
        if (url.searchParams.has('fast')) {
          return route.fulfill({ contentType: 'application/json', body: JSON.stringify(base) })
        }
        if (url.searchParams.has('light')) {
          return route.fulfill({ contentType: 'application/json', body: JSON.stringify(base) })
        }
        if (url.searchParams.get('compact') === '1') compactFullRequests++
        await fullGate
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify({
          ...base, users: { ...base.users, connected_devices: 2 }, vk_hashes: [],
          vk_users: [], vk_hash_summary: { total_active: 0, per_user_active: 0,
            legacy_orphan: 0, users_total: 0, users_with_any: 0,
            users_complete: 0, users_online: 0, slots_max: 3 },
        }) })
      }
      if (url.pathname === '/api/admin/users/paged') {
        userRequests.push(url.search)
        const q = url.searchParams.get('q')
        const p = Number(url.searchParams.get('page'))
        const items = q ? [user('target', 'target@example.test')]
          : p === 1 ? [user('first', 'first@example.test')]
            : [user('second', 'second@example.test')]
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify({
          items, total: 1200, matched: q ? 1 : 1200, page: p, page_size: 50,
        }) })
      }
      return route.fulfill({ status: 404, contentType: 'application/json', body: '{}' })
    })

    await page.goto('http://127.0.0.1:3012/dashboard')
    await page.getByText('Загрузка списка VK-хешей…').waitFor({ timeout: 2500 })
    await page.getByText('Загрузка статистики...').waitFor({ state: 'hidden' })
    releaseFull()
    await page.getByText('Серверные VK-хеши (по пользователям)').waitFor()

    await page.goto('http://127.0.0.1:3012/users')
    await page.getByText('first@example.test').waitFor()
    await page.getByText('1200 из 1200').waitFor()
    await page.getByRole('button', { name: 'Вперёд' }).click()
    await page.getByText('second@example.test').waitFor()
    await page.getByPlaceholder('Поиск по email или ID…').fill('target')
    await page.getByText('target@example.test').waitFor()
    await page.getByText('1 из 1200').waitFor()
    assert(userRequests.some(q => q.includes('page=2')))
    assert(userRequests.some(q => q.includes('q=target')))
    assert.equal(compactFullRequests, 1)
    assert.deepEqual(errors, [])
    console.log('ok: fast dashboard first paint; paged Users navigation and global search')
  } finally {
    await browser.close()
  }
})().catch(error => { console.error(error); process.exitCode = 1 })
