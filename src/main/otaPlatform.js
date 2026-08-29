/** OTA platform id for update API. Linux ≠ Windows installer. */
function otaPlatform(platformHint) {
  if (platformHint) {
    const p = String(platformHint).toLowerCase()
    if (p === 'linux' || p === 'android' || p === 'pc') return p
  }
  return process.platform === 'linux' ? 'linux' : 'pc'
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
