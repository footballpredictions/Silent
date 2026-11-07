const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const root = path.join(__dirname, '..')
const main = fs.readFileSync(path.join(root, 'src/main/main.js'), 'utf8')
const prepare = main.match(/function prepareBrowserRoutingPolicy\(\) \{[\s\S]*?\n\}/)[0]

for (const platform of ['win32', 'linux', 'darwin']) {
  test(`${platform} production session and initial native policy keep selected apps with RU ON`, () => {
    let enabled = false
    const russian = { enabled: () => enabled, configure: () => ({ snapshot: () => ({ enabled }) }) }
    const module = { exports: {} }
    vm.runInNewContext(fs.readFileSync(path.join(root, 'src/main/apps/vpnAppExclusions.js'), 'utf8'), {
      module, process: { platform },
      require(name) {
        if (name === './russianServices') return russian
        if (name === './exclusionsPolicy') return { isProcessExcluded: () => true }
        if (name === './appExclusionBypass') return { startAppExclusionBypass() {}, stopAppExclusionBypass: async () => {}, refreshAppExclusionBypassAfterTunnel: async () => {} }
        throw new Error('Unexpected system dependency: ' + name)
      },
    })
    const apps = module.exports
    const selected = platform === 'win32' ? 'C:\\Apps\\game.exe' : platform === 'darwin' ? '/Applications/MAX.app' : '/usr/bin/firefox'
    apps.setActiveExcludedExePaths([selected])
    const context = vm.createContext({ russianServices: russian, app: { getPath: () => '/unused-fixture' },
      require(name) {
        if (name === './apps/vpnAppExclusions') return apps
        if (name === './apps/siteBypass') return { defaultSiteBypassPath: () => '/unused', loadSiteBypassState: () => ({ rules: [], whitelist: false }), initialBrowserPolicy: () => ({ targets: [], domains: [] }) }
        throw new Error('Unexpected system dependency: ' + name)
      },
    })
    vm.runInContext(prepare, context)
    for (const next of [false, true, false, true]) {
      enabled = next
      assert.deepEqual(Array.from(apps.getActiveExcludedExePaths()), [selected])
      assert.deepEqual(Array.from(vm.runInContext('prepareBrowserRoutingPolicy()', context).excluded), [selected])
      assert.deepEqual(Array.from(apps.applyAppExclusionsForSession([selected], undefined, { enableBypass: false }).applied), [selected])
    }
  })
}

test('Linux accepts ELF paths and keeps case-sensitive application selections distinct', () => {
  const module = { exports: {} }
  vm.runInNewContext(fs.readFileSync(path.join(root, 'src/main/apps/exclusionsPolicy.js'), 'utf8'), { module, process: { platform: 'linux' } })
  const policy = module.exports
  const resolved = policy.resolveBypassExePaths({ selectedIds: ['a', 'b'], apps: [
    { id: 'a', exePath: '/usr/bin/Firefox' }, { id: 'b', exePath: '/usr/bin/firefox' },
  ] })
  assert.equal(resolved.exePaths.length, 2)
  assert.equal(policy.isBypassTarget('firefox'), true)
  assert.equal(policy.isBypassTarget('/usr/bin/fi\nrefox'), false)
})
