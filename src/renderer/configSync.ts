import api, { isLoggedIn } from './api'
import { pushLog } from './debugLog'
import {
  type SyncStateResponse,
  getSyncHashesRev,
  getSyncProfileRev,
  getSyncThemeRev,
  saveSyncHashesRev,
  saveSyncProfileRev,
  saveSyncThemeRev,
  clearSyncRevisions,
} from './syncStateStore'
import { mapHashesResponse, saveHashItems } from './hashItemsStore'
import { saveCachedTheme } from './themeStore'
import { saveCachedProfile } from './profileStore'
import { profileSyncFingerprint } from './profileFingerprint'
import type { ClientTheme } from './clientTheme'
import { flushPendingHashFailures } from './hashFailureReporter'

/** Фоновый sync раз в час — как Android ConfigSyncCoordinator. */
const POLL_MS = 60 * 60 * 1000
const START_DELAY_MS = 5_000
const SYNC_STATE_TIMEOUT_MS = 45_000

let lastProfileFingerprint = ''

export interface ConfigSyncOptions {
  onTheme: (theme: ClientTheme) => void
  onProfile: (profile: unknown) => void
  onHashesUpdated: () => void
  isVpnConnected: () => boolean
  isPollAllowed: () => boolean
}

let pollTimer: ReturnType<typeof setInterval> | null = null
let startTimer: ReturnType<typeof setTimeout> | null = null
let tickInFlight = false
let opts: ConfigSyncOptions | null = null

async function withSyncApi<T>(block: () => Promise<T>): Promise<T> {
  return block()
}

async function fetchSyncState(): Promise<SyncStateResponse | null> {
  try {
    const res = await withSyncApi(() =>
      api.get<SyncStateResponse>('/api/vpn/sync-state', {
        params: {
          hashes_since: getSyncHashesRev(),
          theme_since: getSyncThemeRev(),
          profile_since: getSyncProfileRev(),
        },
        timeout: SYNC_STATE_TIMEOUT_MS,
      }),
    )
    return res.data
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    // Капча / settle после WG — не засоряем лог ECONNABORTED/ETIMEDOUT.
    if (!/CAPTCHA_BUSY|paused during captcha|ECONNABORTED|ETIMEDOUT|ECONNRESET/i.test(msg)) {
      pushLog('ConfigSync', `sync-state: ${msg}`, 'W')
    }
    return null
  }
}

export async function seedConfigSyncRevision(): Promise<void> {
  if (!isLoggedIn()) return
  const state = await fetchSyncState()
  if (!state) return
  saveSyncHashesRev(state.hashes)
  saveSyncThemeRev(state.theme)
  saveSyncProfileRev(state.profile)
}

async function tick(): Promise<void> {
  if (!opts || !isLoggedIn() || !opts.isPollAllowed() || tickInFlight) return
  tickInFlight = true
  try {
    void flushPendingHashFailures()
    const state = await fetchSyncState()
    if (!state) return

    const needHashes = state.changed?.includes('hashes') ?? state.hashes > getSyncHashesRev()
    const needTheme = state.changed?.includes('theme') ?? state.theme > getSyncThemeRev()
    const needProfile = state.changed?.includes('profile') ?? state.profile > getSyncProfileRev()
    const vpnUp = opts.isVpnConnected()

    if (!needHashes && !needTheme && !needProfile && !vpnUp) return

    if (needHashes || needTheme || needProfile) {
      pushLog('ConfigSync', `sync: hashes=${needHashes} theme=${needTheme} profile=${needProfile}`)
    }

    if (needHashes) {
      try {
        const res = await withSyncApi(() => api.get('/api/vpn/hashes'))
        const items = mapHashesResponse(res.data)
        if (items.length > 0) {
          saveHashItems(items)
          saveSyncHashesRev(state.hashes)
          opts.onHashesUpdated()
          pushLog('ConfigSync', `hashes updated (${items.length})`)
        }
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e)
        pushLog('ConfigSync', `hashes fetch: ${msg}`, 'W')
      }
    }

    if (needTheme) {
      try {
        const res = await withSyncApi(() => api.get('/api/vpn/theme'))
        if (res.data) {
          saveCachedTheme(res.data)
          saveSyncThemeRev(state.theme)
          opts.onTheme(res.data as ClientTheme)
          pushLog('ConfigSync', 'theme updated')
        }
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e)
        pushLog('ConfigSync', `theme fetch: ${msg}`, 'W')
      }
    }

    if (needProfile) {
      try {
        const res = await withSyncApi(() => api.get('/api/users/me'))
        if (res.data) {
          const fp = profileSyncFingerprint(res.data)
          saveCachedProfile(res.data)
          saveSyncProfileRev(state.profile)
          if (fp !== lastProfileFingerprint) {
            lastProfileFingerprint = fp
            opts.onProfile(res.data)
            pushLog('ConfigSync', 'profile updated')
          }
        }
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e)
        pushLog('ConfigSync', `profile fetch: ${msg}`, 'W')
      }
    }

    // Main VPN: сверяем подписку (rev мог не измениться при истечении на сервере).
    if (vpnUp) {
      try {
        const res = await withSyncApi(() => api.get('/api/users/me'))
        if (res.data) {
          opts.onProfile(res.data)
          pushLog(
            'ConfigSync',
            `subscription check active=${(res.data as { subscription?: { is_active?: boolean } }).subscription?.is_active ?? '?'}`,
          )
        }
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e)
        pushLog('ConfigSync', `subscription profile: ${msg}`, 'W')
      }
    }
  } finally {
    tickInFlight = false
  }
}

export function startConfigSync(options: ConfigSyncOptions): void {
  stopConfigSync()
  opts = options
  startTimer = setTimeout(() => {
    void tick()
    pollTimer = setInterval(() => {
      void tick()
    }, POLL_MS)
  }, START_DELAY_MS)
}

export function stopConfigSync(): void {
  if (startTimer) {
    clearTimeout(startTimer)
    startTimer = null
  }
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  opts = null
  tickInFlight = false
}

export function resetConfigSyncOnLogout(): void {
  stopConfigSync()
  clearSyncRevisions()
  lastProfileFingerprint = ''
}

export async function tickConfigSyncNow(): Promise<void> {
  await tick()
}
