/** Прогрев DNS/TCP через VPN: YouTube + Telegram media/preview. */

const YOUTUBE_URLS = [
  'https://www.youtube.com/generate_204',
  'https://i.ytimg.com/favicon.ico',
  'https://www.gstatic.com/generate_204',
]

/** Превью/CDN — отдельно от api (в ленте крутится превью, плеер по тапу уже ок). */
const TELEGRAM_URLS = [
  'https://telegram.org/',
  'https://core.telegram.org/',
  'https://api.telegram.org/',
  'https://cdn1.telegram.org/',
  'https://cdn2.telegram.org/',
  'https://cdn3.telegram.org/',
  'https://cdn4.telegram.org/',
  'https://venus.web.telegram.org/',
  'https://flora.web.telegram.org/',
]

let warmupInFlight: Promise<void> | null = null

export function warmupBrowsingPath(timeoutMs = 5_000): Promise<void> {
  if (warmupInFlight) return warmupInFlight
  warmupInFlight = runWarmup(timeoutMs).finally(() => { warmupInFlight = null })
  return warmupInFlight
}

async function runWarmup(timeoutMs: number): Promise<void> {
  const urls = [...YOUTUBE_URLS, ...TELEGRAM_URLS]
  const ctrl = new AbortController()
  const timer = window.setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    let next = 0
    const probe = async () => {
      while (next < urls.length && !ctrl.signal.aborted) {
        const url = urls[next++]
        try {
          await fetch(url, {
            method: 'HEAD',
            mode: 'no-cors',
            cache: 'no-store',
            signal: ctrl.signal,
          })
        } catch { /* warming is best effort */ }
      }
    }
    await Promise.allSettled([
      probe(), probe(), probe(),
      (window as any).electronAPI?.warmupTelegramPath?.().catch(() => null),
    ])
  } finally {
    clearTimeout(timer)
  }
}
