/** Unknown UDP must never be rendered as a successful direct-connect check. */
const assert = require('node:assert/strict')
const path = require('node:path')
const { chromium } = require('../admin-ui/node_modules/playwright')
const root = path.resolve(__dirname, '../..')
;(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true })
  let cases = 0
  try {
    for (const width of [1280, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } })
      let mode = 'unknown'
      const errors = []
      page.on('pageerror', e => errors.push(e.message))
      await page.addInitScript(() => localStorage.setItem('admin_token', 'fixture'))
      await page.route('**/api/admin/**', async route => {
        const pathname = new URL(route.request().url()).pathname
        let data = {}
        if (pathname.endsWith('/cells')) data = []
        if (pathname.endsWith('/sessions')) data = { sessions: [] }
        if (pathname.endsWith('/availability')) {
          const action = mode === 'relay' ? 'relay' : mode === 'hold' ? 'hold' : 'direct'
          const quality = mode === 'legacy' ? {} : { ru_udp_status: mode === 'reachable' ? 'reachable' : action === 'direct' ? 'unverified' : 'unreachable' }
          data = { settings: { enabled: true, interval_sec: 1800, ru_nodes: 3, world_nodes: 2 },
            report: { ts: new Date().toISOString(), status: 'ok', summary: 'Результаты проверок', duration_sec: 30,
              warnings: [], targets: [], verdicts: [], vantage: { ru_nodes: ['ru1', 'ru2'] },
              relay_plan: { action, title: mode === 'legacy' ? 'Сервер 4 доступен напрямую' : mode === 'reachable' ? 'Сервер 4: UDP-проба прошла, прямой маршрут' : mode === 'relay' ? 'Сервер 4: вход через Сота 1' : mode === 'hold' ? 'Сервер 4: UDP-пробы не прошли, подтверждённого входа нет' : 'Сервер 4: прямой маршрут, UDP не подтверждён',
                explain: mode === 'legacy' ? 'С РФ UDP доходит' : 'Результат измерения', executed: false, ...quality,
                hops: [{ name: 'сота3', host: '192.0.2.4', ai_exit: true, action, entry: action === 'relay' ? 'Сота 1' : null,
                  exit: 'сота3', reason: action, explain: '', ...quality }] } } }
        }
        await route.fulfill({ contentType: 'application/json', body: JSON.stringify(data) })
      })
      for (mode of ['unknown', 'legacy', 'reachable', 'relay', 'hold']) {
        await page.goto('http://127.0.0.1:3012/hive')
        await page.getByText('Доступность серверов', { exact: true }).click()
        await page.getByRole('button', { name: /План маршрута:/ }).click()
        if (['unknown', 'legacy'].includes(mode)) {
          await page.getByText('Прямой маршрут оставлен без изменения.', { exact: false }).waitFor()
          const body = await page.locator('body').innerText()
          assert(!body.includes('UDP доходит') && !body.includes('доступен напрямую'))
          assert(body.includes('прямой маршрут · UDP из РФ не подтверждён'))
        } else if (mode === 'reachable') await page.getByText('Сервер 4: UDP-проба прошла, прямой маршрут', { exact: false }).waitFor()
        else if (mode === 'relay') await page.getByText('сота3: вход через другую соту ← Сота 1', { exact: false }).waitFor()
        else await page.getByText('подтверждённого входа нет', { exact: false }).waitFor()
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
        if (mode === 'unknown') {
          await page.getByRole('button', { name: /План маршрута:/ }).scrollIntoViewIfNeeded()
          await page.screenshot({ path: path.join(root, `.playwright-mcp/relay-evidence-${width}-20261109.png`) })
        }
        cases++
      }
      assert.deepEqual(errors, [])
      await page.close()
    }
    console.log(`PASS ${cases} routing-plan states: unknown/legacy/success/relay/hold at 1280/390`)
  } finally { await browser.close() }
})().catch(e => { console.error(e); process.exitCode = 1 })
