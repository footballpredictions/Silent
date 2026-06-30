const { BrowserWindow } = require('electron')

const INTERCEPTOR_JS = `
(function() {
  if (window.__wdtt_interceptor_installed) return;
  window.__wdtt_interceptor_installed = true;
  window.__wdtt_captcha_token = '';
  window.__wdtt_captcha_error = '';
  window.__wdtt_captcha_slider = false;

  function handleData(data) {
    try {
      const resp = data && data.response;
      if (resp && resp.success_token) {
        window.__wdtt_captcha_token = resp.success_token;
        return;
      }
      if (resp && resp.show_captcha_type === 'slider') {
        window.__wdtt_captcha_slider = true;
        window.__wdtt_captcha_error = 'slider_detected';
      } else if (data && data.error) {
        window.__wdtt_captcha_error = JSON.stringify(data.error);
      }
    } catch (e) {}
  }

  const origFetch = window.fetch;
  window.fetch = async function() {
    const response = await origFetch.apply(this, arguments);
    try {
      const url = String(arguments[0] || '');
      if (url.includes('captchaNotRobot.check')) {
        const clone = response.clone();
        handleData(await clone.json());
      }
    } catch (e) {}
    return response;
  };

  const origOpen = XMLHttpRequest.prototype.open;
  const origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(method, url) {
    this._wdtt_url = url;
    return origOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function() {
    const xhr = this;
    if (xhr._wdtt_url && String(xhr._wdtt_url).includes('captchaNotRobot.check')) {
      xhr.addEventListener('load', function() {
        try { handleData(JSON.parse(xhr.responseText)); } catch (e) {}
      });
    }
    return origSend.apply(this, arguments);
  };
})();
`

// Returns the center coordinates of the captcha checkbox, or null if not found.
const FIND_CHECKBOX_JS = `
(function() {
  const el =
    document.querySelector('label.vkc__Checkbox-module__Checkbox') ||
    document.querySelector('[class*="Checkbox"][class*="label"]') ||
    document.querySelector('[class*="checkbox"]') ||
    document.querySelector('[class*="Checkbox"]') ||
    document.querySelector('label[for]') ||
    document.querySelector('input[type="checkbox"]');
  if (!el) return null;
  const rect = el.getBoundingClientRect();
  if (rect.width < 4 || rect.height < 4) return null;
  return {
    x: Math.round(rect.left + rect.width  * (0.3 + Math.random() * 0.4)),
    y: Math.round(rect.top  + rect.height * (0.3 + Math.random() * 0.4))
  };
})()
`

let activeWin = null
let activeSolve = null

function destroyActive() {
  if (activeWin && !activeWin.isDestroyed()) {
    try { activeWin.close() } catch {}
  }
  activeWin = null
}

function cancelCaptchaSolve() {
  if (activeSolve) {
    activeSolve.reject(new Error('superseded'))
    activeSolve = null
  }
  destroyActive()
}

function solveVkCaptcha(redirectUri, mode = 'auto') {
  cancelCaptchaSolve()

  const timeoutMs = mode === 'manual' ? 90_000 : 28_000
  const showWindow = mode === 'manual'

  return new Promise((resolve, reject) => {
    activeSolve = { resolve, reject }
    const win = new BrowserWindow({
      width: 420,
      height: 520,
      show: false,
      skipTaskbar: !showWindow,
      autoHideMenuBar: true,
      title: mode === 'manual' ? 'VK — подтвердите, что вы не робот' : 'Silent VPN',
      webPreferences: {
        nodeIntegration: false,
        contextIsolation: true,
      },
    })
    activeWin = win

    // For auto mode: window must be "visible" to Chromium so the page loads and
    // renders properly (show:false causes ERR_FAILED on id.vk.ru captcha URLs).
    // We show it at opacity=0 so the OS renders it but the user sees nothing.
    if (!showWindow) {
      win.setOpacity(0)
      win.showInactive()
    }

    let settled = false
    const finish = (fn, val) => {
      if (settled) return
      settled = true
      activeSolve = null
      destroyActive()
      fn(val)
    }

    const deadline = Date.now() + timeoutMs
  const poll = async () => {
      if (settled || win.isDestroyed()) return
      try {
        const state = await win.webContents.executeJavaScript(
          `({ token: window.__wdtt_captcha_token || '', err: window.__wdtt_captcha_error || '', slider: !!window.__wdtt_captcha_slider })`,
          true,
        )
        if (state.token) {
          finish(resolve, state.token)
          return
        }
        if (state.slider && mode !== 'manual') {
          // Slider challenge: show window to user for manual solve instead of failing.
          // Keep polling — when user solves it the token will appear.
          mode = 'manual'
          if (!win.isDestroyed()) {
            try {
              win.setOpacity(1.0)
              win.show()
              win.setSkipTaskbar(false)
              win.focus()
            } catch {}
          }
        }
      } catch {
        /* page loading */
      }
      if (Date.now() >= deadline) {
        finish(reject, new Error('captcha timeout'))
        return
      }
      setTimeout(poll, 400)
    }

    let networkRetries = 0

    const loadCaptchaPage = () => {
      win.loadURL(redirectUri).catch(() => {
        // Recoverable load errors are retried in did-fail-load; avoid racing finish(reject).
      })
    }

    win.webContents.on('did-fail-load', (_event, errorCode, errorDescription, validatedURL, isMainFrame) => {
      if (settled || !isMainFrame) return
      // ERR_NETWORK_CHANGED (-21): WireGuard tunnel came up while page was loading — retry.
      if (errorCode === -21 && networkRetries < 4) {
        networkRetries++
        setTimeout(() => {
          if (!settled && !win.isDestroyed()) loadCaptchaPage()
        }, 1500 + networkRetries * 1000)
        return
      }
      finish(reject, new Error(`${errorDescription} (${errorCode}) loading '${validatedURL}'`))
    })

    win.webContents.on('did-finish-load', async () => {
      try {
        await win.webContents.executeJavaScript(INTERCEPTOR_JS, true)
      } catch {}

      if (mode !== 'manual') {
        // Attempt to click the captcha checkbox using trusted OS-level input events
        // (isTrusted: true) so VK cannot detect automation via event.isTrusted check.
        // We try three times at increasing delays in case the page/checkbox loads late.
        const tryClick = async () => {
          if (settled || win.isDestroyed()) return
          try {
            const pos = await win.webContents.executeJavaScript(FIND_CHECKBOX_JS, true)
            if (pos && typeof pos.x === 'number' && typeof pos.y === 'number') {
              // Move, then press, then release — real OS-level events
              win.webContents.sendInputEvent({ type: 'mouseMove', x: pos.x, y: pos.y })
              await new Promise(r => setTimeout(r, 40 + Math.floor(Math.random() * 80)))
              win.webContents.sendInputEvent({ type: 'mouseDown', button: 'left', x: pos.x, y: pos.y, clickCount: 1 })
              await new Promise(r => setTimeout(r, 30 + Math.floor(Math.random() * 60)))
              win.webContents.sendInputEvent({ type: 'mouseUp', button: 'left', x: pos.x, y: pos.y, clickCount: 1 })
              return true
            }
          } catch {}
          return false
        }

        // Kick off click attempts at 1.5s, 4s, 8s, 13s, 20s after page load.
        // Extra late attempts catch slow-loading pages or pages that re-render after initial load.
        for (const delay of [1500 + Math.floor(Math.random() * 800), 4000, 8000, 13000, 20000]) {
          setTimeout(tryClick, delay)
        }
      }

      poll()
    })

    win.on('closed', () => {
      if (!settled) finish(reject, new Error('captcha window closed'))
    })

    loadCaptchaPage()
  })
}

module.exports = { solveVkCaptcha, cancelCaptchaSolve }
