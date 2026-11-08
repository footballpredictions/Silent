/** Real built admin: stale/unknown online, older API compatibility, explicit probe scope. */
const assert = require('node:assert/strict')
const path = require('node:path')
const { chromium } = require('../admin-ui/node_modules/playwright')
const root = path.resolve(__dirname, '../..')

;(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true })
  let cases = 0
  try {
    for (const [width, height] of [[1280, 900], [390, 844]]) {
      const page = await browser.newPage({ viewport: { width, height } })
      const errors = []
      let state = 'fresh'
      page.on('pageerror', e => errors.push(e.message))
      await page.addInitScript(() => localStorage.setItem('admin_token', 'fixture'))
      await page.route('**/api/admin/**', async route => {
        const pathname = new URL(route.request().url()).pathname
        const quality = state === 'legacy' ? {} : {
          online_status: state, online_stale_nodes: state === 'stale' ? ['Сота 1'] : [],
          online_unknown_nodes: state === 'unknown' ? ['Сота 1'] : [],
        }
        let data = {}
        if (pathname.endsWith('/sessions')) data = { sessions: [] }
        if (pathname.endsWith('/incidents')) data = { items: [] }
        if (pathname.endsWith('/stats')) data = {
          users: { total: 200, active_subscriptions: 190, connected_devices: state === 'unknown' ? null : 134, ...quality },
          system: { node_id: 'queen', cpu_percent: 10, memory_percent: 25, memory_total_gb: 8,
            memory_used_gb: 2, network_mbps_rx: 10, network_mbps_tx: 2 }, vk_hashes: [], vk_users: [],
        }
        if (pathname.endsWith('/cells')) data = [
          { id: 'cell1', name: 'Сота 1', is_queen: false, status: 'active', public_ip: '192.0.2.1',
            wdtt_port: 56000, wg_port: 51820, max_online: 90, online_count: state === 'unknown' ? 1 : 30,
            ...(state === 'legacy' ? {} : { online_status: state }), assigned_devices: 50 },
          { id: 'queen', name: 'Улей', is_queen: true, status: 'active', public_ip: '192.0.2.2',
            wdtt_port: 56000, max_online: 190, online_count: 104, online_status: 'fresh', assigned_devices: 150 },
        ]
        if (pathname.endsWith('/summary')) data = { queen_load: {}, all_cells_full: false }
        if (pathname.endsWith('/availability')) data = {
          settings: { enabled: true, interval_sec: 1800, ru_nodes: 3, world_nodes: 2, external_enabled: true },
          report: { ts: new Date().toISOString(), status: 'ok', duration_sec: 45,
            summary: 'Проверены доступные каналы', warnings: [], targets: [],
            vantage: { ru_nodes: ['ru1', 'ru2'], checks: 6 },
            verdicts: [{ kind: 'probe_unconfirmed', target: 'Сота 2', title: 'Внешняя проверка не подтверждена',
              channel: 'agent_tcp', severity: 'info', confidence: 0.4, evidence: [], fixes: [], commands: [] }] },
        }
        await route.fulfill({ contentType: 'application/json', body: JSON.stringify(data) })
      })
      for (state of ['fresh', 'stale', 'unknown', 'legacy']) {
        for (const route of ['dashboard', 'hive']) {
          await page.goto(`http://127.0.0.1:3012/${route}`)
          if (state === 'stale') await page.getByRole('status').filter({ hasText: 'Последнее измерение: Сота 1' }).waitFor()
          else if (state === 'unknown') await page.getByRole('status').filter({ hasText: 'Онлайн не подтверждён: Сота 1' }).waitFor()
          else await page.getByText('134', { exact: true }).first().waitFor()
          if (state === 'unknown') {
            assert.equal(await page.getByText('105', { exact: true }).count(), 0)
            assert(await page.getByText('—', { exact: true }).count() > 0)
          }
          if (route === 'hive') {
            await page.getByText('Доступность серверов', { exact: true }).click()
            await page.getByText('Часть проверок не подтверждена', { exact: true }).waitFor()
            await page.getByText('Полная VPN-сессия', { exact: false }).waitFor()
            assert((await page.locator('body').innerText()).includes('точки РФ: 2 из 3 запрошенных'))
          }
          assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${route}/${state}/${width} overflows`)
          if (['stale', 'unknown'].includes(state)) await page.screenshot({ path: path.join(root, `.playwright-mcp/online-quality-${route}-${state}-${width}.png`), fullPage: true })
          cases++
        }
      }
      assert.deepEqual(errors, [])
      await page.close()
    }
    console.log(`PASS ${cases} real admin states: 1280/390, fresh/stale/unknown/legacy, dashboard/hive`)
  } finally { await browser.close() }
})().catch(e => { console.error(e); process.exitCode = 1 })
