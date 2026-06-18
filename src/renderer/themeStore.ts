import type { ClientTheme } from './clientTheme'

const THEME_KEY = 'silent_cached_theme_json'

export function saveCachedTheme(theme: ClientTheme): void {
  try {
    localStorage.setItem(THEME_KEY, JSON.stringify(theme))
  } catch {
    /* ignore quota */
  }
}

export function getCachedTheme(): ClientTheme | null {
  try {
    const raw = localStorage.getItem(THEME_KEY)
    if (!raw) return null
    return JSON.parse(raw) as ClientTheme
  } catch {
    return null
  }
}
