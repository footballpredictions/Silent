/** Local failures and incomplete coverage must be understandable in the real UI. */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('../admin-ui/node_modules/playwright')
const root = path.resolve(__dirname, '../..')
fs.mkdirSync(path.join(root, '.playwright-mcp'), { recursive:true })
const captured = {
  settings:{ enabled:true, interval_sec:1800, ru_nodes:3, world_nodes:2, external_enabled:true, last_run:null, last_status:'ok' },
  report:{ ts:'2026-10-30T19:24:08+00:00', status:'ok', summary:'Проверенные каналы доступны',
    duration_sec:2, warnings:[], vantage:{}, verdicts:[], targets:[
      { name:'Улей', host:'198.51.100.1', role:'queen', online_count:10, peer:{}, world:{},
        local:{ api_http:{channel:'api_http',ok:true}, dns:{channel:'dns',ok:true},
          wdtt_udp:{channel:'wdtt_udp',ok:true,inconclusive:true} },
        ru:{ api_tcp:{ok:2,failed:0,total:2,error_kinds:{},nodes:[]} } },
      { name:'Сота 2', host:'198.51.100.2', role:'cell', online_count:10, local:{}, world:{}, ru:{},
        peer:{ queen_wdtt:{channel:'queen_wdtt',ok:true,inconclusive:true,detail:'нет ответа (норма UDP)'} } },
    ] },
}
const phase = process.env.AVAILABILITY_CAPTURE_PHASE || 'after'

;(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true })
  const failures = []
  try {
    for (const [name, viewport] of [['desktop', { width:1280, height:900 }], ['mobile', { width:390, height:844 }]]) {
      const page = await browser.newPage({ viewport })
      const errors = []
      let mode = 'local'
      page.on('pageerror', error => errors.push(error.message))
      await page.addInitScript(() => localStorage.setItem('admin_token', 'fixture'))
      await page.route('**/api/admin/**', async route => {
        const pathname = new URL(route.request().url()).pathname
        let data = {}
        if (pathname.endsWith('/cells')) data = []
        if (pathname.endsWith('/sessions')) data = { sessions:[] }
        if (pathname.endsWith('/availability')) {
          data = structuredClone(captured)
          const report = data.report
          report.status = mode === 'local' ? 'degraded' : 'ok'
          data.settings.last_status = report.status
          report.summary = mode === 'local' ? 'Локальная HTTP-проверка не прошла' : 'Проверенные каналы доступны; часть проверок не подтверждена.'
          const queen = report.targets.find(target => target.role === 'queen')
          queen.local.api_http = { channel:'api_http', ok:mode !== 'local', error_kind:mode === 'local' ? 'timeout' : '', detail:mode === 'local' ? 'ConnectTimeout' : 'HTTP 200' }
          queen.local.dns = { channel:'dns', ok:true, error_kind:'', detail:'198.51.100.1' }
          report.verdicts = mode === 'local' ? [{ target:queen.name, host:queen.host,
            kind:'local_health', channel:'api_http', severity:'warning', confidence:0.8,
            title:'Локальная проверка не прошла', summary:'Ошибка локального HTTP', evidence:['ConnectTimeout'], fixes:[], commands:[] }] : [
            { target:queen.name, host:queen.host, kind:'ok', channel:'', severity:'info', confidence:0.9,
              title:'Сервер доступен', summary:'Проверенные каналы доступны', evidence:[], fixes:[], commands:[] },
            { target:'Сота 2', host:'198.51.100.2', kind:'probe_unconfirmed', channel:'agent_tcp', severity:'info', confidence:0.4,
              title:'Внешняя проверка не подтверждена', summary:'Недостаточно измерений', evidence:[], fixes:[], commands:[] }]
        }
        await route.fulfill({ contentType:'application/json', body:JSON.stringify(data) })
      })
      const open = async () => {
        await page.goto('http://127.0.0.1:3012/hive')
        await page.getByText('Доступность серверов', { exact:true }).click()
      }
      await open()
      await page.getByRole('button', { name:'Показать детали по узлам и каналам' }).click()
      await page.screenshot({ path:path.join(root, `.playwright-mcp/availability-local-${phase}-${name}.png`), fullPage:true })
      try {
        const row = page.getByRole('row').filter({ hasText:'HTTP-ответ' })
        assert(await row.getByText('Локально: ConnectTimeout', { exact:true }).isVisible(), 'Local cause missing from the error column')
      } catch (error) { failures.push(name + ': ' + error.message) }
      mode = 'partial'
      await open()
      await page.screenshot({ path:path.join(root, `.playwright-mcp/availability-partial-${phase}-${name}.png`), fullPage:true })
      try {
        assert(await page.getByText('Часть проверок не подтверждена', { exact:true }).isVisible(), 'Incomplete coverage has no scoped status')
        assert.equal(await page.getByText('Доступно из РФ', { exact:true }).count(), 0)
        assert.deepEqual(errors, [])
      } catch (error) { failures.push(name + ': ' + error.message) }
      await page.close()
    }
    assert.deepEqual(failures, [])
    console.log('ok: local causes and incomplete coverage visible at 1280/390px; no page errors')
  } finally { await browser.close() }
})().catch(error => { console.error(error); process.exitCode = 1 })
