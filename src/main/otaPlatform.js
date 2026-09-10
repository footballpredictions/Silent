/** OTA platform id for update API. Linux/mac ≠ Windows installer. */
function otaPlatform(platformHint) {
  if (platformHint) {
    const p = String(platformHint).toLowerCase()
    if (p === 'linux' || p === 'android' || p === 'pc' || p === 'mac' || p === 'macos' || p === 'darwin') {
      if (p === 'macos' || p === 'darwin') return 'mac'
      return p === 'mac' ? 'mac' : p
    }
  }
  if (process.platform === 'linux') return 'linux'
  if (process.platform === 'darwin') return 'mac'
  return 'pc'
}

function wdttBinaryName(platform = process.platform) {
  return platform === 'win32' ? 'wdtt-client.exe' : 'wdtt-client'
}

function killOrphanWdttCmd(platform = process.platform) {
  if (platform === 'win32') {
    return { cmd: 'taskkill', args: ['/F', '/IM', 'wdtt-client.exe'] }
  }
  return { cmd: 'pkill', args: ['-x', 'wdtt-client'] }
}

module.exports = { otaPlatform, wdttBinaryName, killOrphanWdttCmd }
