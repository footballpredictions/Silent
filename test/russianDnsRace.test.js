const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { createRequire } = require('node:module')

for (const platform of ['Linux', 'Darwin']) {
  test(`${platform} background DNS guard cannot overtake Russian policy ACK`, async () => {
    const filename = require.resolve(`../src/main/vpn/wireguard${platform}`)
    const module = { exports: {} }
    const observed = { dns: null }
    let release, reached
    const blocked = new Promise(resolve => { release = resolve })
    const writing = new Promise(resolve => { reached = resolve })
    const context = vm.createContext({ module, require: createRequire(filename), process,
      __dirname: path.dirname(filename), observed, blocked, reached })
    vm.runInContext(fs.readFileSync(filename, 'utf8') + `
      helperOut = async args => {
        if (args[0] === 'russian-policy') return '{"ok":true}';
        if (args[0] !== 'dns-set') throw new Error('Unexpected system operation');
        observed.dns = args[2];
        if (args[2] === '10.66.66.53') { reached(); await blocked; }
        return 'OK';
      };
      savedPhysicalGateway = { nextHop: '192.0.2.1', alias: 'wan0' };
      lastAppliedDns = '9.9.9.9';
      enableLanProtect = async () => {};
      blockIpv6Leak = async () => {};
      module.exports.russianDnsState = () => russianDnsEnabled;
    `, context)
    const toggle = module.exports.updateRussianPolicy({ russian: { enabled: true } })
    await writing
    const guard = module.exports.refreshTunnelGuards(() => {})
    await new Promise(resolve => setImmediate(resolve))
    release()
    await Promise.all([toggle, guard])
    assert.equal(module.exports.russianDnsState(), true)
    assert.equal(observed.dns, '10.66.66.53', 'Guard overwrote the DNS required by the acknowledged RU policy')
  })
}
