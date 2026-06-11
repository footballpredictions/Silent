const SERVER_URL_KEY = 'silent_server_url'
const FALLBACK_PUBLIC = 'https://132-243-234-162.nip.io'

function getPublicServerUrl(): string {
  const stored = localStorage.getItem(SERVER_URL_KEY) || ''
  return (stored || FALLBACK_PUBLIC).replace(/\/$/, '')
}

/** WG gateway на сервере — API в белых списках (как Android WG_TUNNEL_GATEWAY). */
export const WG_TUNNEL_GATEWAY = '10.66.66.1'

let tunnelApiBase: string | null = null

/** Включить tunnel API только когда WG реально поднят (bootstrap или основной VPN). */
export function enableTunnelApi() {
  tunnelApiBase = `http://${WG_TUNNEL_GATEWAY}:8000`
}

/** Переключить на tunnel только если в конфиге есть WG-адрес (иначе — public HTTPS). */
export function setTunnelApiBase(wgAddress?: string | null) {
  if (!wgAddress?.trim()) {
    clearTunnelApiBase()
    return
  }
  enableTunnelApi()
}

export function clearTunnelApiBase() {
  tunnelApiBase = null
}

export function getApiBaseUrl(): string {
  return tunnelApiBase || getPublicServerUrl()
}

export function isTunnelApiActive(): boolean {
  return !!tunnelApiBase
}
