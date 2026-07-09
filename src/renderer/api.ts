import axios from 'axios'
import { isMainVpnSessionActive } from './tunnelApi'
import { installTunnelApiAdapter } from './tunnelApiClient'
import { getCachedTheme } from './themeStore'
import { standbyApiBasesFromTheme } from './clientTheme'

const SERVER_URL_KEY = 'silent_server_url'
const TOKEN_KEY = 'silent_token'
const REFRESH_KEY = 'silent_refresh'
const FALLBACK_PUBLIC = 'https://132-243-234-162.nip.io'
const SERVER_IP = '132.243.234.162'
const SERVER_HOST = '132-243-234-162.nip.io'
/** Текущий fingerprint сессии (как Android PREF_DEVICE_FP). */
const DEVICE_FP_KEY = 'silent_device_fingerprint'
/** Стабильный id ПК — переживает logout/перелогин (как Android PREF_STABLE_FP). */
const STABLE_FP_KEY = 'silent_stable_device_fp'
const SESSION_DEVICE_KEY = 'silent_session_device_id'
const REMEMBER_ME_KEY = 'silent_remember_me'
const REMEMBER_EMAIL_KEY = 'silent_remember_email'
const REMEMBER_PASSWORD_KEY = 'silent_remember_password'

export function getServerUrl(): string {
  return localStorage.getItem(SERVER_URL_KEY) || ''
}
export function setServerUrl(url: string) {
  localStorage.setItem(SERVER_URL_KEY, url.replace(/\/$/, ''))
}

export function getPublicApiBaseUrl(): string {
  return (getServerUrl() || FALLBACK_PUBLIC).replace(/\/$/, '')
}

/** Публичные URL API: standby-соты из theme, затем основной Улей. */
export function getPublicApiCandidateBases(): string[] {
  const out = new Set<string>()
  standbyApiBasesFromTheme(getCachedTheme()).forEach(u => out.add(u.replace(/\/$/, '')))
  out.add(getPublicApiBaseUrl())
  out.add(getDirectApiBaseUrl())
  return [...out]
}

export function getDirectApiBaseUrl(): string {
  return `https://${SERVER_IP}`
}

const api = axios.create({ timeout: 15000 })
installTunnelApiAdapter(api)

api.interceptors.request.use(cfg => {
  // PC renderer не ходит на http://10.66.66.1 — только public HTTPS.
  // При main VPN запросы идут через main IPC (tunnelApiClient), не через этот baseURL.
  if (!isMainVpnSessionActive()) {
    cfg.baseURL = getPublicApiBaseUrl()
    if (!cfg.timeout || cfg.timeout === 15000) {
      cfg.timeout = 15_000
    }
  } else if (!cfg.timeout || cfg.timeout === 15000) {
    cfg.timeout = 25_000
  }
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) cfg.headers!['Authorization'] = `Bearer ${token}`
  return cfg
})

api.interceptors.response.use(
  r => r,
  async err => {
    const cfg = err.config
    if (err.response?.status === 401) {
      const refresh = localStorage.getItem(REFRESH_KEY)
      if (refresh) {
        try {
          const refreshBase = getPublicApiBaseUrl()
          const res = await axios.post(`${refreshBase}/api/auth/refresh`, { refresh_token: refresh })
          localStorage.setItem(TOKEN_KEY, res.data.access_token)
          localStorage.setItem(REFRESH_KEY, res.data.refresh_token)
          err.config.headers['Authorization'] = `Bearer ${res.data.access_token}`
          return api.request(err.config)
        } catch {
          localStorage.removeItem(TOKEN_KEY)
          localStorage.removeItem(REFRESH_KEY)
          window.location.reload()
        }
      }
    }
    return Promise.reject(err)
  }
)

export function saveTokens(access: string, refresh: string) {
  localStorage.setItem(TOKEN_KEY, access)
  localStorage.setItem(REFRESH_KEY, refresh)
}

export function clearTokens() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(REFRESH_KEY)
}

export function isLoggedIn(): boolean {
  return !!localStorage.getItem(TOKEN_KEY)
}

export function getDeviceFingerprint(): string {
  let fp = localStorage.getItem(DEVICE_FP_KEY)
  if (!fp) {
    const legacy = localStorage.getItem('silent_session_fingerprint')
    if (legacy) {
      fp = legacy
      localStorage.setItem(DEVICE_FP_KEY, legacy)
      localStorage.removeItem('silent_session_fingerprint')
    }
  }
  if (!fp) throw new Error('Session not started')
  return fp
}

/**
 * Стабильный fingerprint ПК (один раз). Без него каждый вход = новый UUID = новый слот → «лимит 3».
 * Как Android: ANDROID_ID / PREF_STABLE_FP.
 */
export function getStableDeviceFingerprint(): string {
  let fp = localStorage.getItem(STABLE_FP_KEY)?.trim() || ''
  if (fp) return fp
  // Миграция: если уже был session fp — закрепить его как стабильный
  const legacy = localStorage.getItem(DEVICE_FP_KEY)?.trim()
  fp = legacy || `pc-${crypto.randomUUID()}`
  localStorage.setItem(STABLE_FP_KEY, fp)
  return fp
}

/** Новая сессия при входе — тот же fingerprint ПК (reuse слота на сервере). */
export function startNewSession(): string {
  clearSessionDeviceId()
  const fp = getStableDeviceFingerprint()
  localStorage.setItem(DEVICE_FP_KEY, fp)
  return fp
}

/** Сброс только session-ключа; стабильный fp ПК не трогаем. */
export function clearSessionFingerprint(): void {
  localStorage.removeItem(DEVICE_FP_KEY)
}

export function hasSessionFingerprint(): boolean {
  return !!localStorage.getItem(DEVICE_FP_KEY)?.trim()
}

export function getSessionDeviceId(): string | null {
  return localStorage.getItem(SESSION_DEVICE_KEY)
}

export function saveSessionDeviceId(id: string): void {
  localStorage.setItem(SESSION_DEVICE_KEY, id)
}

export function clearSessionDeviceId(): void {
  localStorage.removeItem(SESSION_DEVICE_KEY)
}

export function getRememberMe(): boolean {
  return localStorage.getItem(REMEMBER_ME_KEY) === '1'
}

export function getRememberedEmail(): string {
  return getRememberMe() ? (localStorage.getItem(REMEMBER_EMAIL_KEY) || '') : ''
}

export function getRememberedPassword(): string {
  return getRememberMe() ? (localStorage.getItem(REMEMBER_PASSWORD_KEY) || '') : ''
}

export function saveRememberMe(email: string, password: string, remember: boolean): void {
  if (remember) {
    localStorage.setItem(REMEMBER_ME_KEY, '1')
    localStorage.setItem(REMEMBER_EMAIL_KEY, email.trim())
    localStorage.setItem(REMEMBER_PASSWORD_KEY, password)
  } else {
    localStorage.removeItem(REMEMBER_ME_KEY)
    localStorage.removeItem(REMEMBER_EMAIL_KEY)
    localStorage.removeItem(REMEMBER_PASSWORD_KEY)
  }
}

export function formatApiError(err: unknown, fallback: string): string {
  const e = err as { response?: { data?: { detail?: unknown } }; message?: string }
  const detail = e?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((d: { msg?: string } | string) => (typeof d === 'string' ? d : d?.msg || String(d)))
      .join(', ')
  }
  return e?.message || fallback
}

export default api
