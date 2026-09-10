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
})
