const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const vm = require('node:vm')
const { createRequire } = require('node:module')
const { linuxUpdateFormat, linuxUpdateScript } = require('../src/main/linuxUpdate')

function debHeader() {
  return Buffer.from('!<arch>\n' + 'debian-binary'.padEnd(16) + '0'.padEnd(12) +
    '0'.padEnd(6) + '0'.padEnd(6) + '100644'.padEnd(8) + '4'.padEnd(10) + '`\n2.0\n')
}

function fixture(signature, suffix) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'silent-linux-update-'))
  const filename = path.join(directory, `update${suffix}`)
  const descriptor = fs.openSync(filename, 'w')
  fs.writeSync(descriptor, signature)
  fs.ftruncateSync(descriptor, 1_100_000)
  fs.closeSync(descriptor)
  return { filename, directory, close: () => fs.rmSync(directory, { recursive: true, force: true }) }
}

function productionFunction(name, context) {
  const filename = require.resolve('../src/main/main')
  const source = fs.readFileSync(filename, 'utf8')
  const declaration = source.match(new RegExp(`function ${name}\\([^]*?\\n\\}`))[0]
  return vm.runInNewContext(`(${declaration})`, {
    fs, path, Buffer, process: { platform: 'linux', env: {}, execPath: '/opt/silent-vpn/silent-vpn' },
    require: createRequire(filename), ...context,
  })
}

test('Linux OTA accepts the published Debian package rather than reporting non-AppImage corruption', () => {
  const header = debHeader()
  const archive = fixture(header, '.deb')
  try {
    const validate = productionFunction('assertValidUpdatePayload')
    assert.doesNotThrow(() => validate(archive.filename, 1_100_000))
    assert.equal(fs.existsSync(archive.filename), true)
  } finally { archive.close() }
})

test('Linux DEB launcher invokes package installation and never executes the archive', () => {
  const archive = fixture(debHeader(), '.deb')
  try {
    const schedule = productionFunction('scheduleLinuxUpdateAfterExit', {
      app: { getPath: () => archive.directory }, sendLog() {},
      spawn: () => ({ unref() {} }),
    })
    const result = schedule(archive.filename)
    assert.equal(result.ok, true)
    const script = fs.readFileSync(result.batPath, 'utf8')
    assert.match(script, /dpkg/)
    assert.match(script, /pkexec/)
    assert.doesNotMatch(script, /chmod \+x/)
  } finally { archive.close() }
})

test('Linux format validation preserves AppImage and refuses HTML, Windows EXE and unrelated ar archives', () => {
  assert.equal(linuxUpdateFormat(Buffer.from([0x7f, 0x45, 0x4c, 0x46])), 'appimage')
  for (const header of [Buffer.from('<html>error'), Buffer.from('MZ'), Buffer.from('!<arch>\nnot-debian')]) {
    assert.throws(() => linuxUpdateFormat(header))
  }
})

test('Debian installation does not overwrite an existing AppImage and safely quotes downloaded paths', () => {
  const script = linuxUpdateScript({ format: 'deb', setup: "/tmp/it's $(touch NEVER).deb", current: '/home/user/VPN.AppImage', logPath: '/tmp/ota.log', previousLauncher: '/home/user/VPN.AppImage' })
  assert.doesNotMatch(script, /cp -f|chmod \+x/)
  assert.match(script, /unset APPIMAGE APPDIR/)
  assert.match(script, /installation failed or cancelled/)
  assert.match(script, /setup='\/tmp\/it'"'"'s \$\(touch NEVER\)\.deb'/)
})
