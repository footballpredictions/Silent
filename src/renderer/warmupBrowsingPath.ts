/** Прогрев DNS/TCP через VPN перед первым открытием браузера (YouTube). */
export async function warmupBrowsingPath(timeoutMs = 12_000): Promise<void> {
  const urls = [
    'https://www.youtube.com/generate_204',
    'https://i.ytimg.com/favicon.ico',
    'https://www.gstatic.com/generate_204',
  ]
  const ctrl = new AbortController()
  const timer = window.setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    await Promise.allSettled(
      urls.map(url =>
        fetch(url, {
          mode: 'no-cors',
          cache: 'no-store',
          signal: ctrl.signal,
        }),
      ),
    )
  } finally {
    clearTimeout(timer)
  }
}
