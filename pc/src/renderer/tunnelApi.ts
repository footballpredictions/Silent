const SERVER_URL_KEY = 'silent_server_url'
const FALLBACK_PUBLIC = 'https://132-243-234-162.nip.io'

function getPublicServerUrl(): string {
  const stored = localStorage.getItem(SERVER_URL_KEY) || ''
  return (stored || FALLBACK_PUBLIC).replace(/\/$/, '')
}

/** WG gateway на сервере — API в белых списках (как Android WG_TUNNEL_GATEWAY). */
export const WG_TUNNEL_GATEWAY = '10.66.66.1'

const TUNNEL_API_URL = `http://${WG_TUNNEL_GATEWAY}:8000`

let tunnelApiBase: string | null = null
/** Основной VPN включён — все api.* идут на 10.66.66.1, не на nip.io. */
let mainVpnSessionActive = false

export function enableTunnelApi() {
  tunnelApiBase = TUNNEL_API_URL
}

export function setTunnelApiBase(wgAddress?: string | null) {
  if (wgAddress?.trim() || mainVpnSessionActive) {
    enableTunnelApi()
    return
  }
  clearTunnelApiBase()
}

export function setMainVpnSessionActive(active: boolean) {
  mainVpnSessionActive = active
  if (active) {
    enableTunnelApi()
  } else if (!tunnelApiBase) {
    clearTunnelApiBase()
  } else if (tunnelApiBase === TUNNEL_API_URL) {
    clearTunnelApiBase()
  }
}

export function isMainVpnSessionActive(): boolean {
  return mainVpnSessionActive
}

export function clearTunnelApiBase() {
  if (mainVpnSessionActive) return
  tunnelApiBase = null
}

export function getApiBaseUrl(): string {
  if (mainVpnSessionActive || tunnelApiBase) {
    return tunnelApiBase || TUNNEL_API_URL
  }
  return getPublicServerUrl()
}

export function isTunnelApiActive(): boolean {
  return mainVpnSessionActive || !!tunnelApiBase
}
