const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')

test('second instance during quit does not touch a destroyed BrowserWindow', () => {
  const source = fs.readFileSync(require.resolve('../src/main/main'), 'utf8')
  const callback = source.match(/app\.on\('second-instance', (\(_, argv\) => \{[\s\S]*?\n  \})\)/)[1]
  let deepLinks = 0
  const handler = vm.runInNewContext(`(${callback})`, {
    mainWindow: {
      isDestroyed: () => true,
      isMinimized() { throw Error('Object has been destroyed') },
    },
    isQuitting: true,
    handleDeepLink() { deepLinks++ },
  })
  assert.doesNotThrow(() => handler({}, ['silentvpn://payment']))
  assert.equal(deepLinks, 0)
})
