const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const ts = require('typescript')

function prepareHarness({ hashes = ['cached-hash'], preferred = true } = {}) {
  const calls = []
  const modules = {
    './api': { default: { get: async (...args) => { calls.push(args); throw Error('offline') }, post: async (...args) => { calls.push(args); throw Error('offline') } } },
    './hashChannelHelper': { applyWorkerCountForConnect: c => c },
    './dnsPreset': { getDnsOverrideServers: () => null },
    './hashItemsStore': { getSavedHashItems: () => hashes.map(hash => ({ hash })), activeServerHashes: a => a, saveHashItems() {}, mapHashesResponse: a => a },
    './debugLog': { pushLog() {} },
    './bypassStore': { cachedConfigMatchesPreferred: () => preferred, getPreferredServer: () => 'cell1' },
  }
  const code = ts.transpileModule(fs.readFileSync(require.resolve('../src/renderer/prepareVpnConnect.ts'), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const exports = {}
  vm.runInNewContext(code, { exports, require: name => modules[name], setTimeout: () => 0 })
  return { prepare: exports.prepareVpnConnectConfig, calls }
}

test('usable cached config with one hash starts without waiting for unavailable public hash/config APIs', async () => {
  const { prepare, calls } = prepareHarness()
  const config = { device_id: 'fixture', server_ip: '192.0.2.1', wg_private_key: 'fixture', server_public_key: 'fixture', vk_hashes: ['cached-hash'] }
  const result = await prepare(config, 'fixture')
  assert.equal(calls.length, 0, 'one usable hash must not wait for hash sync, refresh and config before VPN')
  assert.deepEqual(Array.from(result.vk_hashes), ['cached-hash'])
})
