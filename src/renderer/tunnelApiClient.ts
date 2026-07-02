import type { AxiosRequestConfig, AxiosResponse } from 'axios'
import axios from 'axios'
import { isMainVpnSessionActive } from './tunnelApi'
import { getDirectApiBaseUrl } from './api'

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
  const base = (config.baseURL || '').replace(/\/$/, '')
  const url = config.url || ''
  if (/^https?:\/\//i.test(url)) {
    const u = new URL(url)
    return u.pathname + u.search
  }
  return (url.startsWith('/') ? url : `/${url}`) + (base ? '' : '')
}

export function installTunnelApiAdapter(instance: ReturnType<typeof axios.create>): void {
  const xhrAdapter = axios.getAdapter('xhr')
  instance.defaults.adapter = async (config) => {
    if (isMainVpnSessionActive() && electronTunnel()?.tunnelApiRequest) {
      const headers: Record<string, string> = {}
      const raw = config.headers
      if (raw && typeof raw === 'object') {
        for (const [k, v] of Object.entries(raw)) {
          if (v != null && typeof v !== 'object') headers[k] = String(v)
        }
      }
      try {
        const res = await electronTunnel()!.tunnelApiRequest!({
          method: (config.method || 'get').toUpperCase(),
          path: buildTunnelPath(config),
          headers,
          body: config.data,
          timeout: config.timeout || 20_000,
        })
        return {
          data: res.data,
          status: res.status,
          statusText: 'OK',
          headers: {},
          config,
          request: {},
        } as AxiosResponse
      } catch {
        config.baseURL = getDirectApiBaseUrl()
        config.headers = { ...(config.headers as object), Host: '132-243-234-162.nip.io' }
        return xhrAdapter(config)
      }
    }
    return xhrAdapter(config)
  }
}
