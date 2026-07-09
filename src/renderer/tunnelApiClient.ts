import type { AxiosRequestConfig, AxiosResponse } from 'axios'
import axios from 'axios'
import { shouldRouteApiViaMain, getPublicApiBaseUrl } from './tunnelApi'

type TunnelApiElectron = {
  tunnelApiRequest?: (payload: {
    method: string
    path: string
    headers?: Record<string, string>
    body?: unknown
    timeout?: number
  }) => Promise<{ status: number; data: unknown }>
}

function electronTunnel(): TunnelApiElectron | undefined {
  return (window as typeof window & { electronAPI?: TunnelApiElectron }).electronAPI
}

function buildTunnelPath(config: AxiosRequestConfig): string {
  const url = config.url || ''
  if (/^https?:\/\//i.test(url)) {
    const u = new URL(url)
    return u.pathname + u.search
  }
  const path = url.startsWith('/') ? url : `/${url}`
  const params = config.params
  if (!params || typeof params !== 'object') return path
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(params as Record<string, unknown>)) {
    if (v == null) continue
    qs.append(k, String(v))
  }
  const q = qs.toString()
  return q ? `${path}?${q}` : path
}

/** AxiosHeaders: Object.entries часто пустой — нужен toJSON / get. */
function flattenAxiosHeaders(raw: unknown): Record<string, string> {
  const headers: Record<string, string> = {}
  if (!raw || typeof raw !== 'object') return headers
  const anyRaw = raw as { toJSON?: () => Record<string, unknown>; get?: (k: string) => unknown }
  const plain =
    typeof anyRaw.toJSON === 'function'
      ? anyRaw.toJSON()
      : (raw as Record<string, unknown>)
  for (const [k, v] of Object.entries(plain || {})) {
    if (v == null || typeof v === 'object') continue
    headers[k] = String(v)
  }
  if (!headers.Authorization && !headers.authorization && typeof anyRaw.get === 'function') {
    const auth = anyRaw.get('Authorization') ?? anyRaw.get('authorization')
    if (auth != null && typeof auth !== 'object') {
      headers.Authorization = String(auth)
    }
  }
  if (!headers.Authorization && !headers.authorization) {
    try {
      const token = localStorage.getItem('silent_token')
      if (token) headers.Authorization = `Bearer ${token}`
    } catch { /* ignore */ }
  }
  return headers
}

export function installTunnelApiAdapter(instance: ReturnType<typeof axios.create>): void {
  const xhrAdapter = axios.getAdapter('xhr')
  instance.defaults.adapter = async (config) => {
    const skipTunnel = Boolean((config as any).__skipTunnel) || Boolean((config as any).__forcePublic)
    // Bootstrap или main VPN: API через main → 10.66.66.1 (как Android). Renderer xhr на public часто timeout.
    if (!skipTunnel && shouldRouteApiViaMain() && electronTunnel()?.tunnelApiRequest) {
      const headers = flattenAxiosHeaders(config.headers)
      // Axios мог уже stringify — нормализуем тело для IPC
      let body: unknown = config.data
      if (body != null && typeof body === 'object' && !(body instanceof ArrayBuffer)) {
        body = JSON.stringify(body)
        if (!headers['Content-Type'] && !headers['content-type']) {
          headers['Content-Type'] = 'application/json'
        }
      }
      try {
        const res = await electronTunnel()!.tunnelApiRequest!({
          method: (config.method || 'get').toUpperCase(),
          path: buildTunnelPath(config),
          headers,
          body: body ?? null,
          timeout: config.timeout || 25_000,
        })
        if (res.status >= 200 && res.status < 300) {
          return {
            data: res.data,
            status: res.status,
            statusText: 'OK',
            headers: {},
            config,
            request: {},
          } as AxiosResponse
        }
        const detail = (res.data as any)?.detail
        const msg =
          typeof detail === 'string'
            ? detail
            : Array.isArray(detail)
              ? detail.map((d: any) => d?.msg || String(d)).join(', ')
              : `HTTP ${res.status}`
        const err: any = new Error(msg)
        err.config = config
        err.response = { status: res.status, data: res.data, headers: {}, config }
        err.isAxiosError = true
        throw err
      } catch (e: any) {
        if (e?.isAxiosError) throw e
        const err: any = new Error(e?.message || 'API request failed')
        err.config = config
        err.isAxiosError = true
        throw err
      }
    }
    if (!config.baseURL) {
      config.baseURL = getPublicApiBaseUrl()
    }
    return xhrAdapter(config)
  }
}
