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

const CLICK_JS = `
(function() {
  const label = document.querySelector('label.vkc__Checkbox-module__Checkbox') ||
    document.querySelector('[class*="Checkbox"]') ||
    document.querySelector('input[type="checkbox"]');
  if (!label) return false;
  const rect = label.getBoundingClientRect();
  const x = rect.left + rect.width * (0.35 + Math.random() * 0.3);
  const y = rect.top + rect.height * (0.35 + Math.random() * 0.3);
  const el = document.elementFromPoint(x, y) || label;
  el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, clientX: x, clientY: y }));
  el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, clientX: x, clientY: y }));
  el.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: x, clientY: y }));
  if (typeof label.click === 'function') label.click();
  return true;
})();
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

  const timeoutMs = mode === 'manual' ? 90_000 : 25_000
  const showWindow = mode === 'manual'

  return new Promise((resolve, reject) => {
    activeSolve = { resolve, reject }
    const win = new BrowserWindow({
      width: 420,
      height: 520,
      show: showWindow,
      autoHideMenuBar: true,
      title: mode === 'manual' ? 'VK — подтвердите, что вы не робот' : 'Silent VPN',
      webPreferences: {
        nodeIntegration: false,
        contextIsolation: true,
      },
    })
    activeWin = win

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
          finish(reject, new Error('slider_detected'))
          return
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

    win.webContents.on('did-finish-load', async () => {
      try {
        await win.webContents.executeJavaScript(INTERCEPTOR_JS, true)
        if (mode !== 'manual') {
          setTimeout(async () => {
            try { await win.webContents.executeJavaScript(CLICK_JS, true) } catch {}
          }, 1200 + Math.floor(Math.random() * 800))
        }
      } catch {}
      poll()
    })

    win.on('closed', () => {
      if (!settled) finish(reject, new Error('captcha window closed'))
    })

    win.loadURL(redirectUri).catch(err => finish(reject, err))
  })
}

module.exports = { solveVkCaptcha, cancelCaptchaSolve }
