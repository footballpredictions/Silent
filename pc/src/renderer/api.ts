import axios from 'axios'

const SERVER_URL_KEY = 'silent_server_url'
const TOKEN_KEY = 'silent_token'
const REFRESH_KEY = 'silent_refresh'

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

export default api
