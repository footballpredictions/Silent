const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const { createRequire } = require('node:module')
const path = require('node:path')

for (const platform of ['win32', 'linux', 'darwin']) {
  test(`Russian services supported on ${platform}`, () => {
    const filename = require.resolve('../src/main/apps/russianServices')
    const module = { exports: {} }
    vm.runInNewContext(fs.readFileSync(filename, 'utf8'), {
      module, require: createRequire(filename), process: { platform },
    }, { filename })
    assert.equal(module.exports.supported(), true)
  })
}

for (const platform of ['Linux', 'Darwin']) {
  test(`${platform} requires native ACK and routes DNS into TUN; OFF restores DNS`, async () => {
    const filename = require.resolve(`../src/main/vpn/wireguard${platform}`)
    const module = { exports: {} }
    const calls = []
    let reject = false
    const context = vm.createContext({
      module, require: createRequire(filename), process, __dirname: path.dirname(filename),
      calls, nativeReply: () => reject ? '{"ok":false}' : '{"ok":true}',
    })
    vm.runInContext(fs.readFileSync(filename, 'utf8') + `
      helperOut = async args => { calls.push(args); return args[0] === 'russian-policy' ? nativeReply() : 'OK'; };
      savedPhysicalGateway = { nextHop:'192.0.2.1', alias:'wan0' };
      lastAppliedDns = '9.9.9.9, 1.1.1.1';
    `, context)
    const router = module.exports
    await router.updateRussianPolicy({ russian: { enabled: true, direct_domains: ['ru'] } })
    assert.equal(calls[0][0], 'russian-policy')
    assert.equal(JSON.parse(calls[0][1]).russian.enabled, true)
    assert.deepEqual(Array.from(calls[1]), ['dns-set', router.TUNNEL_NAME, '10.66.66.53'])
    assert.deepEqual(JSON.parse(calls[0][1]).dns, ['9.9.9.9', '1.1.1.1'])
    await router.updateRussianPolicy({ russian: { enabled: false } })
    assert.match(calls.at(-1)[2], /9\.9\.9\.9/)
    assert.doesNotMatch(calls.at(-1)[2], /10\.66\.66\.53/)
    const before = calls.length
    reject = true
    await assert.rejects(router.updateRussianPolicy({ russian: { enabled: true } }))
    assert.equal(calls.length, before + 1, 'DNS must not change without native ACK')
  })
}
