/** Detect a new publication when an old tab is restored or brought to the foreground. */
export function watchAdminVersion() {
  const loadedAssets = [...new Set(
    Array.from(document.querySelectorAll('script[type="module"][src],link[rel="stylesheet"][href],link[rel="modulepreload"][href]'))
      .map(element => element.getAttribute('src') || element.getAttribute('href') || '')
      .filter(url => url.startsWith('/assets/'))
  )].sort()
  if (!loadedAssets.length) return

  const reloadKey = 'silent_admin_version_reload'
  let pending = false
  let reloading = false
  let lastCheck = -Infinity

  const check = async (force = false) => {
    if (pending || reloading || document.visibilityState === 'hidden') return
    if (!force && performance.now() - lastCheck < 15_000) return
    pending = true
    lastCheck = performance.now()
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 3_000)
    try {
      const response = await fetch('/admin-ui-version.json', { cache: 'no-store', signal: controller.signal })
      if (!response.ok) return
      const current = await response.json() as { version?: string; assets?: unknown }
      if (!current.version || !Array.isArray(current.assets) || !current.assets.length) return
      if (!current.assets.every(asset => typeof asset === 'string' && asset.startsWith('/assets/'))) return
      if (JSON.stringify([...current.assets].sort()) === JSON.stringify(loadedAssets)) {
        try { sessionStorage.removeItem(reloadKey) } catch { /* Storage can be disabled. */ }
        return
      }
      // At most one reload per published version, including proxy/cache misconfiguration.
      try {
        if (sessionStorage.getItem(reloadKey) === current.version) return
        sessionStorage.setItem(reloadKey, current.version)
      } catch {
        // The URL also bounds reloads when session storage is disabled.
        if (new URL(location.href).searchParams.get('__ui_version') === current.version) return
        const url = new URL(location.href)
        url.searchParams.set('__ui_version', current.version)
        reloading = true
        location.replace(url)
        return
      }
      reloading = true
      location.reload()
    } catch {
      // A failed version probe must not prevent login or normal admin operations.
    } finally {
      window.clearTimeout(timeout)
      pending = false
    }
  }

  window.addEventListener('pageshow', event => { if (event.persisted) void check(true) })
  window.addEventListener('focus', () => { void check() })
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') void check(true)
  })
  void check(true)
}
