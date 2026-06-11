import axios from 'axios'
import { getApiBaseUrl, isTunnelApiActive } from './tunnelApi'

const SERVER_URL_KEY = 'silent_server_url'
const TOKEN_KEY = 'silent_token'
const REFRESH_KEY = 'silent_refresh'
const FALLBACK_PUBLIC = 'https://132-243-234-162.nip.io'
/** Один fingerprint на сессию — как Android PREF_DEVICE_FP. */
const DEVICE_FP_KEY = 'silent_device_fingerprint'
const SESSION_DEVICE_KEY = 'silent_session_device_id'
const REMEMBER_ME_KEY = 'silent_remember_me'
const REMEMBER_EMAIL_KEY = 'silent_remember_email'

export function getServerUrl(): string {
  return localStorage.getItem(SERVER_URL_KEY) || ''
}
export function setServerUrl(url: string) {
  localStorage.setItem(SERVER_URL_KEY, url.replace(/\/$/, ''))
}

export function getPublicApiBaseUrl(): string {
  return (getServerUrl() || FALLBACK_PUBLIC).replace(/\/$/, '')
}

const api = axios.create({ timeout: 15000 })

api.interceptors.request.use(cfg => {
  cfg.baseURL = isTunnelApiActive() ? getApiBaseUrl() : getPublicApiBaseUrl()
  if (!cfg.timeout || cfg.timeout === 15000) {
    cfg.timeout = isTunnelApiActive() ? 45_000 : 15_000
  }
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) cfg.headers!['Authorization'] = `Bearer ${token}`
  return cfg
})

api.interceptors.response.use(
  r => r,
  async err => {
    if (err.response?.status === 401) {
      const refresh = localStorage.getItem(REFRESH_KEY)
      if (refresh) {
        try {
          const res = await axios.post(`${getPublicApiBaseUrl()}/api/auth/refresh`, { refresh_token: refresh })
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

/** Новая сессия при входе — освобождает слот устройства (как Android). */
export function startNewSession(): string {
  clearSessionDeviceId()
  const fp = crypto.randomUUID()
  localStorage.setItem(DEVICE_FP_KEY, fp)
  return fp
}

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

export function saveRememberMe(email: string, remember: boolean): void {
  if (remember) {
    localStorage.setItem(REMEMBER_ME_KEY, '1')
    localStorage.setItem(REMEMBER_EMAIL_KEY, email.trim())
  } else {
    localStorage.removeItem(REMEMBER_ME_KEY)
    localStorage.removeItem(REMEMBER_EMAIL_KEY)
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
