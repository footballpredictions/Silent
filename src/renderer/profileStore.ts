const PROFILE_KEY = 'silent_cached_profile_json'

export function saveCachedProfile(profile: unknown): void {
  try {
    localStorage.setItem(PROFILE_KEY, JSON.stringify(profile))
  } catch {
    /* ignore quota */
  }
}

export function getCachedProfile<T = Record<string, unknown>>(): T | null {
  try {
    const raw = localStorage.getItem(PROFILE_KEY)
    if (!raw) return null
    return JSON.parse(raw) as T
  } catch {
    return null
  }
}

export function clearCachedProfile(): void {
  localStorage.removeItem(PROFILE_KEY)
}
