import type { ClientTheme } from './clientTheme'
import { standbyApiBasesFromTheme } from './clientTheme'

const THEME_KEY = 'silent_cached_theme_json'

function pushStandbyToMain(theme: ClientTheme): void {
  const urls = standbyApiBasesFromTheme(theme)
  const electron = (window as unknown as { electronAPI?: { setStandbyApiBases?: (u: string[]) => void } }).electronAPI
  try {
    electron?.setStandbyApiBases?.(urls)
  } catch {
    /* ignore */
  }
}

export function saveCachedTheme(theme: ClientTheme): void {
  try {
    localStorage.setItem(THEME_KEY, JSON.stringify(theme))
  } catch {
    /* ignore quota */
  }
  pushStandbyToMain(theme)
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
