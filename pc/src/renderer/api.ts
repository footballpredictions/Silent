import axios from 'axios'

const SERVER_URL_KEY = 'silent_server_url'
const TOKEN_KEY = 'silent_token'
const REFRESH_KEY = 'silent_refresh'
const DEVICE_FP_KEY = 'silent_device_fingerprint'
const SESSION_FP_KEY = 'silent_session_fingerprint'
const SESSION_DEVICE_KEY = 'silent_session_device_id'

export function getServerUrl(): string {
  return localStorage.getItem(SERVER_URL_KEY) || ''
}
export function setServerUrl(url: string) {
  localStorage.setItem(SERVER_URL_KEY, url.replace(/\/$/, ''))
}

const api = axios.create({ timeout: 15000 })

api.interceptors.request.use(cfg => {
  const baseURL = getServerUrl()
  cfg.baseURL = baseURL
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
          const res = await axios.post(`${getServerUrl()}/api/auth/refresh`, { refresh_token: refresh })
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
    fp = crypto.randomUUID()
    localStorage.setItem(DEVICE_FP_KEY, fp)
  }
  return fp
}

export function startNewSession(): string {
  const fp = crypto.randomUUID()
  localStorage.setItem(SESSION_FP_KEY, fp)
  return fp
}

export function clearSessionFingerprint(): void {
  localStorage.removeItem(SESSION_FP_KEY)
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
