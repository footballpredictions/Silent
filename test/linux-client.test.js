/**
 * Linux PC-клиент: тот же VPN/UI-контракт, что Windows.
 * Запуск: npm test
 */
const { describe, it } = require('node:test')
const assert = require('node:assert/strict')

const { otaPlatform, wdttBinaryName, killOrphanWdttCmd } = require('../src/main/otaPlatform')
const {
  parseDesktop,
  firstArg,
  looksLikeApp,
} = require('../src/main/apps/listInstalledAppsLinux')
const {
  parseBypassTarget,
  buildAllowedIPsForLinux,
  normalizeDnsValue,
  SYSTEM_HELPER,
  HELPER_SOCK,
} = require('../src/main/vpn/wireguardLinux')
const { packsForExePaths } = require('../src/main/apps/platformBypassPacks')

describe('otaPlatform', () => {
  it('keeps pc/android/linux hints', () => {
    assert.equal(otaPlatform('pc'), 'pc')
    assert.equal(otaPlatform('linux'), 'linux')
    assert.equal(otaPlatform('android'), 'android')
  })
  it('wdtt binary name is not .exe on linux', () => {
    assert.equal(wdttBinaryName('linux'), 'wdtt-client')
    assert.equal(wdttBinaryName('win32'), 'wdtt-client.exe')
  })
  it('kill cmd is pkill on linux', () => {
    const k = killOrphanWdttCmd('linux')
    assert.equal(k.cmd, 'pkill')
    assert.ok(k.args.includes('wdtt-client'))
  })
})

describe('linux desktop parser', () => {
  it('parses Name/Exec and strips field codes', () => {
    const d = parseDesktop(`[Desktop Entry]
Type=Application
Name=Firefox
Exec=/usr/bin/firefox %u
Icon=firefox
`)
    assert.equal(d.Name, 'Firefox')
    assert.equal(firstArg(d.Exec), '/usr/bin/firefox')
    assert.equal(looksLikeApp(d), true)
  })
  it('skips NoDisplay', () => {
    const d = parseDesktop(`[Desktop Entry]
Type=Application
Name=Hidden
Exec=/bin/true
NoDisplay=true
`)
    assert.equal(looksLikeApp(d), false)
  })
})

describe('linux wireguard contract matches Windows', () => {
  it('full tunnel AllowedIPs are /1+/1 not 0.0.0.0/0', () => {
    const logs = []
    const allowed = buildAllowedIPsForLinux(['1.2.3.4'], (m) => logs.push(m))
    assert.equal(allowed, '0.0.0.0/1, 128.0.0.0/1')
  })
  it('bypass target parses ip and cidr', () => {
    assert.deepEqual(parseBypassTarget('10.1.2.3'), { ip: '10.1.2.3', prefix: 32, dest: '10.1.2.3/32' })
    assert.equal(parseBypassTarget('8.8.8.8/32').dest, '8.8.8.8/32')
    assert.equal(parseBypassTarget('not-an-ip'), null)
  })
  it('DNS override same as PC', () => {
    assert.equal(normalizeDnsValue('77.88.8.8', '1.1.1.1'), '1.1.1.1')
    assert.ok(normalizeDnsValue('10.66.66.1', '').includes('10.66.66.1'))
  })
  it('uses system helper socket so toggle is not pkexec-per-call', () => {
    assert.equal(SYSTEM_HELPER, '/usr/libexec/silent-vpn-wg-helper')
    assert.equal(HELPER_SOCK, '/run/silent-vpn/helper.sock')
  })
  it('dns bypass targets include cloudflare/yandex /32', () => {
    const { dnsBypassIps } = require('../src/main/vpn/wireguardLinux')
    const ips = dnsBypassIps('1.1.1.1, 1.0.0.1, 77.88.8.8')
    assert.ok(ips.includes('1.1.1.1/32'))
    assert.ok(ips.includes('77.88.8.8/32'))
    assert.ok(ips.includes('8.8.8.8/32'), 'Google DNS always bypassed (DHCP leftover)')
  })
  it('hostPinPairsFromMap builds ip:host for Linux hosts-pin', () => {
    const { hostPinPairsFromMap, VK_HOSTS } = require('../src/main/vpn/vkNetworkExcludes')
    assert.ok(VK_HOSTS.includes('calls.okcdn.ru'), 'okcdn needed for VK Calls step4')
    const pairs = hostPinPairsFromMap({
      'api.vk.me': ['87.240.129.140'],
      'api.vk.ru': ['87.240.190.75', 'bad'],
      'calls.okcdn.ru': ['155.212.204.195'],
    })
    assert.ok(pairs.includes('87.240.129.140:api.vk.me'))
    assert.ok(pairs.includes('87.240.190.75:api.vk.ru'))
    assert.ok(pairs.includes('155.212.204.195:calls.okcdn.ru'))
    assert.equal(pairs.length, 3)
  })
})

describe('linux steam/discord pack match', () => {
  it('matches linux steam and dota2 paths', () => {
    const r = packsForExePaths(['/home/u/.steam/steam/steamapps/common/dota 2 beta/game/bin/linuxsteamrt64/dota2'])
    assert.ok(r.packIds.includes('steam'))
  })
  it('matches linux discord binary', () => {
    const r = packsForExePaths(['/usr/share/discord/Discord'])
    assert.ok(r.packIds.includes('discord'))
  })
})
