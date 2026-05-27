/** Парсинг хеша VK — как HashParser.kt на Android. */
export function extractCallHash(raw: string): string | null {
  let s = raw.trim()
  if (!s) return null
  s = s.split('?')[0].split('#')[0].trim().replace(/\/+$/, '')
  const joinMatch = s.match(/\/join\/([A-Za-z0-9_-]+)/i)
  if (joinMatch) return joinMatch[1].replace(/\/+$/, '')
  const joinBare = s.match(/join\/([A-Za-z0-9_-]+)/i)
  if (joinBare) return joinBare[1].replace(/\/+$/, '')
  const bare = s.replace(/^https?:\/\//i, '').replace(/^www\./i, '').trim()
  if (bare.length >= 6 && bare.length <= 128 && /^[A-Za-z0-9_-]+$/.test(bare)) return bare
  return null
}

export function isHashReady(): boolean {
  return !!localStorage.getItem('silent_vk_bootstrap_hash')?.trim()
}
