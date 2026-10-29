/** A failed service API probe must not imply that the VPN itself is blocked. */
const assert = require('node:assert/strict')
const { chromium } = require('../admin-ui/node_modules/playwright')

;(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true })
  try {
    const page = await browser.newPage()
    let vpnFailure = false
    await page.addInitScript(() => localStorage.setItem('admin_token', 'fixture'))
    await page.route('**/api/admin/**', async route => {
      const path = new URL(route.request().url()).pathname
      let data = {}
      if (path.endsWith('/cells')) data = []
      if (path.endsWith('/sessions')) data = { sessions: [] }
      if (path.endsWith('/availability')) data = { settings: { enabled: true, interval_sec: 1800,
        ru_nodes: 3, world_nodes: 2, external_enabled: true, last_run: null, last_status: 'blocked' },
        report: { ts: new Date().toISOString(), status: 'blocked', worst_severity: 'error',
          summary: 'Есть блокировка', duration_sec: 30, warnings: [], vantage: {}, targets: [],
          verdicts: [{ target: 'Сота 2', host: '198.51.100.2', kind: vpnFailure ? 'udp_block' : 'port_block',
            channel: vpnFailure ? 'wdtt_udp' : 'agent_tcp', severity: 'error', confidence: 0.8,
            title: vpnFailure ? 'UDP заблокирован' : 'Блокировка по порту', summary: 'Порт режется',
            evidence: ['Два таймаута проверяющих нод'], fixes: [], commands: [] }] } }
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(data) })
    })
    await page.goto('http://127.0.0.1:3012/hive')
    await page.getByText('Доступность серверов', { exact: true }).click()
    await page.getByText('Проверка доступности', { exact: true }).waitFor()
    assert.equal(await page.getByText('Есть блокировка', { exact: true }).count(), 0,
      'service API-only failures must not display a blanket blocking status')
    await page.getByText('Ограничен доступ к служебному API', { exact: true }).waitFor()
    await page.getByText(/Два таймаута проверяющих нод/).waitFor()
    vpnFailure = true
    await page.reload()
    await page.getByText('Доступность серверов', { exact: true }).click()
    await page.getByText('UDP заблокирован', { exact: true }).waitFor()
    assert(await page.getByText('Есть блокировка', { exact: true }).count() > 0,
      'actual VPN transport evidence must remain visible')
    console.log('ok: service API scope is explicit; VPN transport alarms and evidence are preserved')
  } finally { await browser.close() }
})().catch(error => { console.error(error); process.exitCode = 1 })
