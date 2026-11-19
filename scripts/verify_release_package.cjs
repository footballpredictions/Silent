/* Verify the packaged app, not only the source tree, before publishing it. */
const fs = require('node:fs')
const path = require('node:path')
const crypto = require('node:crypto')
const vm = require('node:vm')
const { execFileSync } = require('node:child_process')
const assert = require('node:assert/strict')
const asar = require('@electron/asar')

const [platform, arch, appDir, expectedVersion, expectedCommit, receiptPath] = process.argv.slice(2)
assert.ok(['win32', 'linux', 'darwin'].includes(platform), 'expected a desktop platform')
assert.ok(['x64', 'arm64'].includes(arch), 'expected a desktop architecture')
assert.match(expectedVersion || '', /^\d+\.\d+\.\d+$/)
assert.match(expectedCommit || '', /^[a-f0-9]{40}$/)
const resources = path.join(appDir, platform === 'darwin' ? 'Contents/Resources' : 'resources')
const archive = path.join(resources, 'app.asar')
const read = name => asar.extractFile(archive, path.normalize(name)).toString('utf8')
const evaluateData = name => {
  const scope = { module: { exports: {} } }
  vm.runInNewContext(read(name), scope)
  return scope.module.exports
}
const digest = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
const pkg = JSON.parse(read('package.json'))
assert.equal(pkg.version, expectedVersion, 'packaged version')
assert.equal(evaluateData('src/main/buildFlags.js').DEBUG_BUILD, false, 'release must disable debug UI/logging')
assert.ok(!asar.listPackage(archive).some(name => /[\\/]dist[\\/]renderer[\\/].*\.map$/.test(name)), 'release sourcemaps')
for (const name of ['src/main/main.js', 'src/main/workerProgress.js', 'src/renderer/prepareVpnConnect.ts', 'src/renderer/warmupBrowsingPath.ts']) {
  assert.equal(read(name), fs.readFileSync(path.join(__dirname, '..', name), 'utf8'), `packaged source: ${name}`)
}

function architecture(file) {
  const b = fs.readFileSync(file)
  assert.ok(b.length > 1000000, `native binary too small: ${file}`)
  if (b.subarray(0, 2).toString() === 'MZ') return b.readUInt16LE(b.readUInt32LE(0x3c) + 4) === 0x8664 ? 'win32/x64' : 'unsupported PE'
  if (b.subarray(0, 4).equals(Buffer.from([0x7f, 0x45, 0x4c, 0x46]))) return b[4] === 2 && b.readUInt16LE(18) === 62 ? 'linux/x64' : 'unsupported ELF'
  if (b.readUInt32LE(0) === 0xfeedfacf) return b.readUInt32LE(4) === 0x100000c ? 'darwin/arm64' : b.readUInt32LE(4) === 0x1000007 ? 'darwin/x64' : 'unsupported Mach-O'
  return 'unsupported native format'
}
const wdtt = path.join(resources, platform === 'win32' ? 'wdtt-client.exe' : 'wdtt-client')
const engine = path.join(resources, platform === 'win32' ? 'wireguard/site-router.exe' : 'wireguard-go')
assert.equal(architecture(wdtt), `${platform}/${arch}`, 'WDTT architecture')
assert.equal(architecture(engine), `${platform}/${arch}`, 'routing engine architecture')
const pinField = platform === 'win32' ? 'WDTT_SHA256' : platform === 'linux' ? 'WDTT_LINUX_SHA256' : 'WDTT_MAC_SHA256'
const pins = evaluateData('src/main/integrityHashes.js')
assert.equal(pins[pinField], digest(wdtt), 'packaged WDTT must match its platform pin')
assert.equal(pins.SOURCE_COMMIT, expectedCommit, 'native hash manifest source commit')
const buildInfo = execFileSync('go', ['version', '-m', wdtt], { encoding: 'utf8' })
if (buildInfo.includes('vcs.revision=')) assert.ok(buildInfo.includes(`vcs.revision=${expectedCommit}`), 'native source commit')
if (platform === 'win32') {
  const exe = fs.readFileSync(path.join(appDir, 'Silent VPN.exe')).toString('utf8')
  assert.match(exe, /requestedExecutionLevel level="requireAdministrator"/, 'administrator launch')
} else {
  const helper = fs.readFileSync(path.join(resources, 'silent-wg-helper'), 'utf8')
  assert.ok(helper.startsWith('#!') && !helper.includes('\r'), 'helper must have an executable LF shebang')
  if (platform === 'darwin') {
    assert.equal(execFileSync('plutil', ['-extract', 'CFBundleShortVersionString', 'raw', '-o', '-', path.join(appDir, 'Contents/Info.plist')], { encoding: 'utf8' }).trim(), expectedVersion, 'macOS app version')
    execFileSync('codesign', ['--verify', '--deep', '--strict', appDir], { stdio: 'pipe' })
    const slice = arch === 'arm64' ? 'arm64' : 'x86_64'
    const python = path.join(resources, 'python/bin/python3')
    assert.ok(execFileSync('lipo', ['-archs', python], { encoding: 'utf8' }).includes(slice), 'bundled Python architecture')
  }
}
const receipt = { version: expectedVersion, source_commit: expectedCommit, platform, arch, debug: false, wdtt_sha256: digest(wdtt), routing_sha256: digest(engine), asar_sha256: digest(archive) }
fs.writeFileSync(receiptPath, JSON.stringify(receipt, null, 2) + '\n')
console.log(`Release package verified: ${platform}/${arch} ${expectedVersion} ${expectedCommit}`)
