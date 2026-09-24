/**
 * Mac PC-клиент: тот же VPN/UI-контракт, что Windows/Linux.
 * Запуск: npm test
 */
const { describe, it } = require('node:test')
const assert = require('node:assert/strict')

const { otaPlatform, wdttBinaryName, killOrphanWdttCmd } = require('../src/main/otaPlatform')
const {
  parseBypassTarget,
  buildAllowedIPsForDarwin,
  normalizeDnsValue,
  SYSTEM_HELPER,
  HELPER_SOCK,
  HELPER_PLIST,
} = require('../src/main/vpn/wireguardDarwin')

describe('otaPlatform mac', () => {
  it('maps darwin/macos hints to mac', () => {
    assert.equal(otaPlatform('mac'), 'mac')
    assert.equal(otaPlatform('macos'), 'mac')
    assert.equal(otaPlatform('darwin'), 'mac')
  })
  it('wdtt binary name is not .exe on darwin', () => {
    assert.equal(wdttBinaryName('darwin'), 'wdtt-client')
  })
  it('kill cmd is pkill on darwin', () => {
    const k = killOrphanWdttCmd('darwin')
    assert.equal(k.cmd, 'pkill')
  })
})

describe('darwin wireguard contract matches Windows/Linux', () => {
  it('full tunnel AllowedIPs are /1+/1', () => {
    assert.equal(buildAllowedIPsForDarwin(['1.2.3.4'], () => {}), '0.0.0.0/1, 128.0.0.0/1')
  })
  it('bypass target parses ip and cidr', () => {
    assert.deepEqual(parseBypassTarget('10.1.2.3'), { ip: '10.1.2.3', prefix: 32, dest: '10.1.2.3/32' })
  })
  it('DNS override same as PC', () => {
    assert.equal(normalizeDnsValue('77.88.8.8', '1.1.1.1'), '1.1.1.1')
  })
  it('uses LaunchDaemon helper paths', () => {
    assert.equal(SYSTEM_HELPER, '/Library/PrivilegedHelperTools/silent-vpn-wg-helper')
    assert.equal(HELPER_SOCK, '/var/run/silent-vpn/helper.sock')
    assert.equal(HELPER_PLIST, '/Library/LaunchDaemons/ru.silent.vpn.helper.plist')
  })
  // Регресс Mac hang: tryApplyWg → resolveWgMtu is not a function (Darwin не экспортировал)
  it('exports resolveWgMtu for main tryApplyWg', () => {
    const wg = require('../src/main/vpn/wireguardDarwin')
    assert.equal(typeof wg.resolveWgMtu, 'function')
    assert.equal(wg.resolveWgMtu({ selected_server: 'server1' }), 1200)
    // Mac clamp ≤1280 (не 1420) — иначе PMTU blackhole при WDTT
    assert.equal(wg.resolveWgMtu({ selected_server: 'server3' }), 1280)
  })
  it('helper cmd_down restores DNS/hosts/IPv6 (no leftover blackhole)', () => {
    const fs = require('fs')
    const path = require('path')
    const helperSrc = fs.readFileSync(
      path.join(__dirname, '../resources/mac/silent-wg-helper'),
      'utf8',
    )
    const downFn = helperSrc.match(/def cmd_down[\s\S]*?(?=\ndef cmd_)/)
    assert.ok(downFn, 'cmd_down present')
    assert.match(downFn[0], /cmd_dns_restore/)
    assert.match(downFn[0], /cmd_ipv6_restore/)
    assert.match(downFn[0], /cmd_hosts_restore/)
  })
  it('helper dns-set skips foreign VPN network services', () => {
    const fs = require('fs')
    const path = require('path')
    const helperSrc = fs.readFileSync(
      path.join(__dirname, '../resources/mac/silent-wg-helper'),
      'utf8',
    )
    assert.match(helperSrc, /_dns_target_services/)
    assert.match(helperSrc, /_SKIP_DNS_SVC/)
    assert.match(helperSrc, /v2box/i)
    assert.match(helperSrc, /happ/i)
    const dnsSet = helperSrc.match(/def cmd_dns_set[\s\S]*?(?=\ndef cmd_)/)
    assert.ok(dnsSet, 'cmd_dns_set present')
    assert.match(dnsSet[0], /_dns_target_services/)
  })
  it('helper kills competitor VPNs before up', () => {
    const fs = require('fs')
    const path = require('path')
    const helperSrc = fs.readFileSync(
      path.join(__dirname, '../resources/mac/silent-wg-helper'),
      'utf8',
    )
    assert.match(helperSrc, /def cmd_competitors_off/)
    assert.match(helperSrc, /"competitors-off":\s*cmd_competitors_off/)
    assert.match(helperSrc, /V2BOX/)
    assert.match(helperSrc, /Happ/)
    assert.match(helperSrc, /v2RayTun/)
    assert.match(helperSrc, /Urban VPN/)
    assert.match(helperSrc, /freevpn/i)
    const upFn = helperSrc.match(/def cmd_up[\s\S]*?(?=\ndef cmd_)/)
    assert.ok(upFn, 'cmd_up present')
    assert.match(upFn[0], /cmd_competitors_off/)
  })
  it('helper protects loopback before full tunnel routes (WDTT :9000)', () => {
    const fs = require('fs')
    const path = require('path')
    const helperSrc = fs.readFileSync(
      path.join(__dirname, '../resources/mac/silent-wg-helper'),
      'utf8',
    )
    assert.match(helperSrc, /def protect_loopback_for_wdtt/)
    assert.match(helperSrc, /127\.0\.0\.0\/8/)
    assert.match(helperSrc, /"handshake":\s*cmd_handshake/)
    const applyFn = helperSrc.match(/def apply_addr_routes[\s\S]*?(?=\ndef )/)
    assert.ok(applyFn, 'apply_addr_routes')
    assert.match(applyFn[0], /protect_loopback_for_wdtt/)
  })
  it('helper DNS targets primary Wi-Fi only + probe command', () => {
    const fs = require('fs')
    const path = require('path')
    const helperSrc = fs.readFileSync(
      path.join(__dirname, '../resources/mac/silent-wg-helper'),
      'utf8',
    )
    assert.match(helperSrc, /_iface_to_service/)
    assert.match(helperSrc, /_default_route_iface/)
    assert.match(helperSrc, /setv6off/)
    assert.match(helperSrc, /"probe":\s*cmd_probe/)
    assert.match(helperSrc, /"reload":\s*cmd_reload/)
    assert.match(helperSrc, /10\.66\.66\.1|create_connection/)
    assert.match(helperSrc, /thunderbolt/i)
  })
  it('silent-wg-helper is valid Python (no JS || typos)', () => {
    const fs = require('fs')
    const path = require('path')
    const { spawnSync } = require('child_process')
    const helperPath = path.join(__dirname, '../resources/mac/silent-wg-helper')
    const src = fs.readFileSync(helperPath, 'utf8')
    assert.doesNotMatch(src, /\|\|/)
    const py = process.platform === 'win32' ? 'python' : 'python3'
    const r = spawnSync(py, ['-m', 'py_compile', helperPath], { encoding: 'utf8' })
    assert.equal(r.status, 0, r.stderr || r.stdout || 'py_compile failed')
  })
  it('helper clears stale 0/1 routes before adding tunnel routes', () => {
    const fs = require('fs')
    const path = require('path')
    const helperSrc = fs.readFileSync(
      path.join(__dirname, '../resources/mac/silent-wg-helper'),
      'utf8',
    )
    assert.match(helperSrc, /clear_stale_split_default_routes/)
    const applyFn = helperSrc.match(/def apply_addr_routes[\s\S]*?(?=\ndef )/)
    assert.ok(applyFn)
    assert.match(applyFn[0], /clear_stale_split_default_routes/)
    assert.match(applyFn[0], /-interface/)
    assert.match(applyFn[0], /alias/)
    assert.match(applyFn[0], /-inet/)
    assert.match(applyFn[0], /check=1\.1\.1\.1|check_ip|10\.66\.66\.1/)
  })
  it('Darwin upgrades system helper from bundled (not SYSTEM path)', () => {
    const fs = require('fs')
    const path = require('path')
    const src = fs.readFileSync(
      path.join(__dirname, '../src/main/vpn/wireguardDarwin.js'),
      'utf8',
    )
    assert.match(src, /function findBundledHelper/)
    assert.match(src, /findBundledHelper\(lastIsDev/)
    assert.match(src, /killCompetitorVpnsLocal/)
    assert.match(src, /unknown command/)
    assert.match(src, /mac-force-helper\.sh/)
    // Тумблер НЕ должен звать osascript/пароль (регресс: цикл пароля)
    assert.doesNotMatch(src, /with administrator privileges/)
    assert.doesNotMatch(src, /execFileAsync\('osascript'/)
    const bundledFn = src.match(/function findBundledHelper[\s\S]*?(?=\nfunction )/)
    assert.ok(bundledFn, 'findBundledHelper body')
    assert.doesNotMatch(bundledFn[0], /PrivilegedHelperTools/)
  })
  // Лог 11:28: phase1 ok → /1 → hive timeout; /24 «активен» = сайты ок / YouTube нет
  it('phase2 collects TURN bypass and fails honestly if full tunnel dies', () => {
    const fs = require('fs')
    const path = require('path')
    const {
      noteTurnEndpointFromLog,
      listTurnBypassIps,
    } = require('../src/main/vpn/wireguardDarwin')
    noteTurnEndpointFromLog('[VK Auth]   [0] turn:91.231.135.149:19302')
    noteTurnEndpointFromLog('turn:95.163.34.174:19302')
    const ips = listTurnBypassIps()
    assert.ok(ips.includes('91.231.135.149'))
    assert.ok(ips.includes('95.163.34.174'))
    // vkcalls (дефолт) печатает без «turn:» — лог 16:56: IP не ловились, phase2 умирал
    noteTurnEndpointFromLog('2026/09/24 16:56:25 [VKCalls] turn_server.urls[0]=155.212.199.165:19302')
    noteTurnEndpointFromLog('[VKCalls] turn_server.urls[1]=87.250.1.2:443')
    assert.ok(listTurnBypassIps().includes('155.212.199.165'))
    assert.ok(listTurnBypassIps().includes('87.250.1.2'))
    const mainSrc = fs.readFileSync(path.join(__dirname, '../src/main/main.js'), 'utf8')
    assert.match(mainSrc, /turn_server\\\.urls/)
    const src = fs.readFileSync(
      path.join(__dirname, '../src/main/vpn/wireguardDarwin.js'),
      'utf8',
    )
    assert.match(src, /ensureTurnBypassBeforeFull/)
    assert.match(src, /return false/)
    assert.match(src, /тумблер OFF|full VPN не активен/)
    assert.doesNotMatch(src, /Туннель активен \(только 10\.66\.66\.0\/24/)
  })
  // Чистая установка из DMG: первый VPN — bootstrap входа, helper должен ставиться из приложения
  it('helper install from app: one prompt per run, script via temp file, syntax check first', async () => {
    const fs = require('fs')
    const path = require('path')
    const mod = require('../src/main/vpn/macHelperInstall')
    const src = fs.readFileSync(path.join(__dirname, '../src/main/vpn/macHelperInstall.js'), 'utf8')
    assert.match(src, /promptedThisRun/)
    assert.match(src, /ast\.parse/)
    assert.match(src, /\/bin\/bash \$\{scriptPath\}/)
    assert.doesNotMatch(src, /JSON\.stringify\(/)
    const script = mod.buildInstallScript({
      helperTmp: '/tmp/x/silent-wg-helper',
      systemHelper: '/Library/PrivilegedHelperTools/silent-vpn-wg-helper',
      plistPath: '/Library/LaunchDaemons/ru.silent.vpn.helper.plist',
      label: 'ru.silent.vpn.helper',
      sockPath: '/var/run/silent-vpn/helper.sock',
    })
    assert.match(script, /launchctl bootstrap system/)
    assert.match(script, /<string>serve<\/string>/)
    mod._resetPromptForTests()
    const logs = []
    const first = await mod.installSystemHelperOnce({ bundledHelper: '/nope', send: (m) => logs.push(m) })
    const second = await mod.installSystemHelperOnce({ bundledHelper: '/nope', send: (m) => logs.push(m) })
    assert.equal(first, false)
    assert.equal(second, false)
    assert.equal(logs.length, 1, 'второй вызов за запуск не должен ничего делать')
    const darwin = fs.readFileSync(path.join(__dirname, '../src/main/vpn/wireguardDarwin.js'), 'utf8')
    assert.match(darwin, /installHelperFromApp\(/)
  })
  it('bundled mac wdtt-client contains IP_BOUND_IF', () => {
    const fs = require('fs')
    const path = require('path')
    const bin = path.join(__dirname, '../resources/mac/wdtt-client')
    assert.ok(fs.existsSync(bin), 'resources/mac/wdtt-client')
    const buf = fs.readFileSync(bin)
    assert.ok(buf.includes(Buffer.from('IP_BOUND_IF')), 'wdtt must embed IP_BOUND_IF')
    assert.ok(buf.includes(Buffer.from('protect=darwin')), 'startup LAN banner')
  })
})

describe('main.js Mac hang guards', () => {
  const fs = require('fs')
  const path = require('path')
  const mainSrc = fs.readFileSync(path.join(__dirname, '../src/main/main.js'), 'utf8')

  // Регресс: vpn-is-ready → ReferenceError wgInstallInFlight is not defined
  it('declares wgInstallInFlight at module scope (not only inside beginWdttSession)', () => {
    const moduleDecl = /^let wgInstallInFlight = false/m.test(mainSrc)
    assert.equal(moduleDecl, true)
    // Не должно быть повторного let внутри beginWdttSession (shadowing)
    const localLets = (mainSrc.match(/^\s+let wgInstallInFlight = false/gm) || []).length
    assert.equal(localLets, 0)
  })
})
