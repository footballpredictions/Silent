/** Current classifier findings must remain scoped and preserve real VPN alarms. */
const assert = require('node:assert/strict')
const { chromium } = require('../admin-ui/node_modules/playwright')

;(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true })
  try {
    const page = await browser.newPage()
    let blocked = false
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.addInitScript(() => localStorage.setItem('admin_token', 'fixture'))
    await page.route('**/api/admin/**', async route => {
      const path = new URL(route.request().url()).pathname
      let data = {}
      if (path.endsWith('/cells')) data = []
      if (path.endsWith('/sessions')) data = { sessions: [] }
      if (path.endsWith('/availability')) data = {
        settings: { enabled: true, interval_sec: 1800, ru_nodes: 3, world_nodes: 2,
          external_enabled: true, last_run: null, last_status: blocked ? 'blocked' : 'degraded' },
        report: { ts: '2026-10-29T17:05:32+00:00', status: blocked ? 'blocked' : 'degraded',
          worst_severity: blocked ? 'error' : 'warning', summary: 'Результаты внешних измерений',
          duration_sec: 30, warnings: [], vantage: {}, targets: [], verdicts: blocked ? [
            { target: 'Улей', host: '198.51.100.1', kind: 'udp_block', channel: 'wdtt_udp',
              severity: 'error', confidence: 0.8, title: 'UDP заблокирован', summary: 'Отказ транспорта',
              evidence: [], fixes: [], commands: [] }
          ] : [
            { target: 'Улей', host: '198.51.100.1', kind: 'https_degraded', channel: 'api_tcp',
              severity: 'warning', confidence: 0.55, title: 'Внешние проверки HTTPS',
              summary: 'Таймаут с двух точек РФ; причина не установлена.',
              evidence: ['Контроль вне РФ: 2/2'], fixes: [], commands: [] },
            { target: 'Сота 2', host: '198.51.100.2', kind: 'probe_unconfirmed', channel: 'agent_tcp',
              severity: 'info', confidence: 0.4, title: 'Внешняя проверка не подтверждена',
              summary: 'Ошибки служебной пробы не доказывают блокировку VPN.',
              evidence: ['Служебный API отвечает с Улья'], fixes: [], commands: [] }
          ] }
      }
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(data) })
    })
    await page.goto('http://127.0.0.1:3012/hive')
    await page.getByText('Доступность серверов', { exact: true }).click()
    await page.getByText('Внешняя проверка не подтверждена', { exact: true }).waitFor()
    await page.getByText('Внешние проверки HTTPS', { exact: true }).waitFor()
    assert.equal(await page.getByText('Есть блокировка', { exact: true }).count(), 0)
    assert.equal(await page.getByText('Ограничен доступ к служебному API', { exact: true }).count(), 0)
    blocked = true
    await page.reload()
    await page.getByText('Доступность серверов', { exact: true }).click()
    await page.getByText('UDP заблокирован', { exact: true }).waitFor()
    assert(await page.getByText('Есть блокировка', { exact: true }).count() > 0)
    assert.deepEqual(errors, [])
    console.log('ok: inconclusive probes have no block banner; confirmed transport alarm retained')
  } finally { await browser.close() }
})().catch(error => { console.error(error); process.exitCode = 1 })
