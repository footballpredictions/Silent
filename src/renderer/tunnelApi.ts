const SERVER_URL_KEY = 'silent_server_url'
const FALLBACK_PUBLIC = 'https://132-243-234-162.nip.io'

function getPublicServerUrl(): string {
  const stored = localStorage.getItem(SERVER_URL_KEY) || ''
  return (stored || FALLBACK_PUBLIC).replace(/\/$/, '')
}

export const WG_TUNNEL_GATEWAY = '10.66.66.1'

let mainVpnSessionActive = false
let wgTunnelReady = false
let tunnelApiActive = false
let tunnelApiBase = `http://${WG_TUNNEL_GATEWAY}:8000`

export function setMainVpnSessionActive(active: boolean) {
  mainVpnSessionActive = active
  if (!active) {
    wgTunnelReady = false
    tunnelApiActive = false
    return
  }
  // Main VPN активен: API должен идти через WG gateway.
  tunnelApiBase = `http://${WG_TUNNEL_GATEWAY}:8000`
  tunnelApiActive = true
}

export function setWgTunnelReady(ready: boolean) {
  wgTunnelReady = ready
}

export function isMainVpnSessionActive(): boolean {
  return mainVpnSessionActive
}

export function getApiBaseUrl(): string {
  return tunnelApiActive ? tunnelApiBase : getPublicServerUrl()
}

export function isTunnelApiActive(): boolean {
  return tunnelApiActive
}

export function getPublicApiBaseUrl(): string {
  return getPublicServerUrl()
}

export function enableTunnelApi() {
  tunnelApiActive = true
}

export function setTunnelApiBase(wgAddress?: string | null) {
  const host = (wgAddress || WG_TUNNEL_GATEWAY).trim()
  tunnelApiBase = `http://${host}:8000`
  tunnelApiActive = true
}

export function clearTunnelApiBase() {
  tunnelApiActive = false
}
