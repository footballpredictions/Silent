const { BrowserWindow } = require('electron')

function parseTokenFromUrl(url) {
  try {
    const u = new URL(url)
    const fragment = u.hash ? u.hash.slice(1) : ''
    const params = new URLSearchParams(fragment)
    const token = params.get('access_token')
    const userId = parseInt(params.get('user_id') || '0', 10)
    if (!token) return null
    return { accessToken: token, userId: Number.isFinite(userId) ? userId : 0 }
  } catch {
    return null
  }
}

function runVkAndroidOAuth(authUrl) {
  return new Promise((resolve, reject) => {
    const win = new BrowserWindow({
      width: 420,
      height: 640,
      show: true,
      autoHideMenuBar: true,
      webPreferences: {
        nodeIntegration: false,
        contextIsolation: true,
      },
      title: 'Вход VK — Silent VPN',
    })

    let settled = false
    const finish = (fn, val) => {
      if (settled) return
      settled = true
      try { if (!win.isDestroyed()) win.close() } catch {}
      fn(val)
    }

    const onRedirect = (_e, url) => {
      if (!url.includes('blank.html')) return
      const parsed = parseTokenFromUrl(url)
      if (parsed) finish(resolve, parsed)
    }

    win.webContents.on('will-redirect', onRedirect)
    win.webContents.on('will-navigate', onRedirect)
    win.on('closed', () => {
      if (!settled) finish(reject, new Error('VK OAuth закрыт'))
    })

    win.loadURL(authUrl).catch(err => finish(reject, err))
  })
}

module.exports = { runVkAndroidOAuth }
