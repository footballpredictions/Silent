/**
 * afterPack Mac: положить wdtt/wireguard в Resources.
 * - fat (universal build): lipo -thin под текущий arch
 * - уже thin (MAC_ARCH=amd64|arm64): просто copy, без -thin
 */
const fs = require('fs')
const path = require('path')
const { execFileSync } = require('child_process')

function thinSliceForArch(arch) {
  if (arch === 1 || arch === 'x64') return 'x86_64'
  if (arch === 3 || arch === 'arm64') return 'arm64'
  return null
}

function lipoInfo(file) {
  try {
    return execFileSync('lipo', ['-info', file], { encoding: 'utf8' }).trim()
  } catch {
    return ''
  }
}

function isFat(file) {
  return /architectures in the fat file/i.test(lipoInfo(file))
}

exports.default = async function macAfterPack(context) {
  if (context.electronPlatformName !== 'darwin') return
  if (process.platform !== 'darwin') return

  const root = path.join(__dirname, '..')
  const srcDir = path.join(root, 'resources', 'mac')
  const product = context.packager.appInfo.productFilename || 'Silent VPN'
  const appPath = path.join(context.appOutDir, `${product}.app`)
  const resources = path.join(appPath, 'Contents', 'Resources')
  if (!fs.existsSync(resources)) {
    console.warn('[mac-after-pack] Resources missing:', resources)
    return
  }

  const slice = thinSliceForArch(context.arch)
  console.log(`[mac-after-pack] arch=${context.arch} want=${slice || 'any'}`)

  for (const name of ['wdtt-client', 'wireguard-go']) {
    const from = path.join(srcDir, name)
    const to = path.join(resources, name)
    if (!fs.existsSync(from)) throw new Error(`mac-after-pack: missing ${from}`)

    if (slice && isFat(from)) {
      const tmp = `${to}.thin`
      execFileSync('lipo', [from, '-thin', slice, '-output', tmp])
      fs.renameSync(tmp, to)
    } else {
      fs.copyFileSync(from, to)
    }
    fs.chmodSync(to, 0o755)
    console.log(`[mac-after-pack] ${name}: ${lipoInfo(to)}`)
  }

  const helperFrom = path.join(srcDir, 'silent-wg-helper')
  const helperTo = path.join(resources, 'silent-wg-helper')
  if (fs.existsSync(helperFrom)) {
    fs.copyFileSync(helperFrom, helperTo)
    fs.chmodSync(helperTo, 0o755)
  }
}
