const SERVER_URL_KEY = 'silent_server_url'

function getPublicServerUrl(): string {
  return localStorage.getItem(SERVER_URL_KEY) || ''
}

/** WG gateway на сервере — API в белых списках (как Android WG_TUNNEL_GATEWAY). */
export const WG_TUNNEL_GATEWAY = '10.66.66.1'

let tunnelApiBase: string | null = null

export function wgGatewayFromAddress(wgAddress?: string | null): string | null {
  if (!wgAddress?.trim()) return WG_TUNNEL_GATEWAY
  const host = wgAddress.split('/')[0].trim()
  if (!host || host === '0.0.0.0') return WG_TUNNEL_GATEWAY
  return WG_TUNNEL_GATEWAY
}

export function setTunnelApiBase(wgAddress?: string | null) {
  const gw = wgGatewayFromAddress(wgAddress)
  if (!gw) {
    clearTunnelApiBase()
    return
  }
  tunnelApiBase = `http://${gw}:8000`
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
