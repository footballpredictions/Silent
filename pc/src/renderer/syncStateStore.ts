const HASHES_REV = 'silent_sync_hashes_rev'
const THEME_REV = 'silent_sync_theme_rev'
const PROFILE_REV = 'silent_sync_profile_rev'

export function getSyncHashesRev(): number {
  return Number(localStorage.getItem(HASHES_REV) || 0)
}

export function getSyncThemeRev(): number {
  return Number(localStorage.getItem(THEME_REV) || 0)
}

export function getSyncProfileRev(): number {
  return Number(localStorage.getItem(PROFILE_REV) || 0)
}

export function saveSyncHashesRev(rev: number): void {
  localStorage.setItem(HASHES_REV, String(rev))
}

export function saveSyncThemeRev(rev: number): void {
  localStorage.setItem(THEME_REV, String(rev))
}

export function saveSyncProfileRev(rev: number): void {
  localStorage.setItem(PROFILE_REV, String(rev))
}

export function maxSyncRev(): number {
  return Math.max(getSyncHashesRev(), getSyncThemeRev(), getSyncProfileRev())
}

export function clearSyncRevisions(): void {
  localStorage.removeItem(HASHES_REV)
  localStorage.removeItem(THEME_REV)
  localStorage.removeItem(PROFILE_REV)
}

export interface SyncStateResponse {
  revision: number
  hashes: number
  theme: number
  profile: number
  changed: string[]
}
