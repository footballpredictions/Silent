/**
 * Unit tests: PC integrity / anti-tamper.
 * Запуск: npm test
 */
const { describe, it } = require('node:test')
const assert = require('node:assert/strict')
const crypto = require('crypto')
const fs = require('fs')
const os = require('os')
const path = require('path')

const {
  verifyWdttIntegrity,
  softTamperHints,
  sha256File,
} = require('../src/main/integrity')

function writeTemp(name, buf) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'silent-int-'))
  const file = path.join(dir, name)
  fs.writeFileSync(file, buf)
  return { dir, file }
}

describe('integrity sha256File', () => {
  it('matches crypto.createHash for known content', () => {
    const { dir, file } = writeTemp('wdtt-client.exe', Buffer.from('hello-silent'))
    try {
      const expected = crypto.createHash('sha256').update('hello-silent').digest('hex')
      assert.equal(sha256File(file), expected)
    } finally {
      fs.rmSync(dir, { recursive: true, force: true })
    }
  })
})

describe('verifyWdttIntegrity gates', () => {
  it('skips when not packaged (dev)', () => {
    const r = verifyWdttIntegrity({
      isPackaged: false,
      isDebugBuild: false,
      exePath: 'missing.exe',
      expectedSha: 'deadbeef',
    })
    assert.equal(r.ok, true)
  })

  it('skips when debug build', () => {
    const r = verifyWdttIntegrity({
      isPackaged: true,
      isDebugBuild: true,
      exePath: 'missing.exe',
      expectedSha: 'deadbeef',
    })
    assert.equal(r.ok, true)
  })

  it('skips when expectedSha empty (legacy package)', () => {
    const logs = []
    const r = verifyWdttIntegrity({
      isPackaged: true,
      isDebugBuild: false,
      exePath: 'missing.exe',
      expectedSha: '',
      log: (m) => logs.push(m),
    })
    assert.equal(r.ok, true)
    assert.ok(logs.some((l) => /WDTT_SHA256 пуст/.test(l)))
  })

  it('fails when exe missing in release', () => {
    const r = verifyWdttIntegrity({
      isPackaged: true,
      isDebugBuild: false,
      exePath: path.join(os.tmpdir(), 'no-such-wdtt-client.exe'),
      expectedSha: 'a'.repeat(64),
    })
    assert.equal(r.ok, false)
    assert.match(r.reason, /не найден/)
  })

  it('passes when hash matches official binary', () => {
    const { dir, file } = writeTemp('wdtt-client.exe', Buffer.from('official-wdtt-bin'))
    try {
      const pin = sha256File(file)
      const r = verifyWdttIntegrity({
        isPackaged: true,
        isDebugBuild: false,
        exePath: file,
        expectedSha: pin,
      })
      assert.equal(r.ok, true)
    } finally {
      fs.rmSync(dir, { recursive: true, force: true })
    }
  })

  it('fails when binary tampered (hash mismatch)', () => {
    const { dir, file } = writeTemp('wdtt-client.exe', Buffer.from('tampered-payload'))
    try {
      const r = verifyWdttIntegrity({
        isPackaged: true,
        isDebugBuild: false,
        exePath: file,
        expectedSha: 'a'.repeat(64),
      })
      assert.equal(r.ok, false)
      assert.match(r.reason, /изменён|повреждён/)
    } finally {
      fs.rmSync(dir, { recursive: true, force: true })
    }
  })

  it('expectedSha is case-insensitive', () => {
    const { dir, file } = writeTemp('wdtt-client.exe', Buffer.from('case-test'))
    try {
      const pin = sha256File(file).toUpperCase()
      const r = verifyWdttIntegrity({
        isPackaged: true,
        isDebugBuild: false,
        exePath: file,
        expectedSha: pin,
      })
      assert.equal(r.ok, true)
    } finally {
      fs.rmSync(dir, { recursive: true, force: true })
    }
  })
})

describe('softTamperHints', () => {
  it('does nothing in debug / unpackaged', () => {
    const logs = []
    softTamperHints({ isPackaged: false, isDebugBuild: false, log: (m) => logs.push(m) })
    softTamperHints({ isPackaged: true, isDebugBuild: true, log: (m) => logs.push(m) })
    assert.equal(logs.length, 0)
  })

  it('warns on ELECTRON_RUN_AS_NODE in release packaged', () => {
    const prev = process.env.ELECTRON_RUN_AS_NODE
    process.env.ELECTRON_RUN_AS_NODE = '1'
    const logs = []
    try {
      softTamperHints({ isPackaged: true, isDebugBuild: false, log: (m) => logs.push(m) })
      assert.ok(logs.some((l) => /ELECTRON_RUN_AS_NODE/.test(l)))
    } finally {
      if (prev === undefined) delete process.env.ELECTRON_RUN_AS_NODE
      else process.env.ELECTRON_RUN_AS_NODE = prev
    }
  })
})

describe('integrityHashes pin present after gen', () => {
  it('integrityHashes.js exports 64-hex WDTT_SHA256 when resources binary exists', () => {
    const exe = path.join(__dirname, '..', 'resources', 'wdtt-client.exe')
    if (!fs.existsSync(exe)) {
      // CI без бинаря — skip
      return
    }
    const hashes = require('../src/main/integrityHashes')
    assert.match(hashes.WDTT_SHA256, /^[a-f0-9]{64}$/)
    assert.equal(hashes.WDTT_SHA256, sha256File(exe))
  })
})
