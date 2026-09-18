const SERVER_URL_KEY = 'silent_server_url'
const FALLBACK_PUBLIC = 'https://89-125-188-100.nip.io'

function getPublicServerUrl(): string {
  const stored = localStorage.getItem(SERVER_URL_KEY) || ''
  return (stored || FALLBACK_PUBLIC).replace(/\/$/, '')
}

export const WG_TUNNEL_GATEWAY = '10.66.66.1'
/** Админка при VPN и без — публичный nip.io (трафик через туннель на слоте соты). */
export const PUBLIC_ADMIN_URL = `${FALLBACK_PUBLIC}/dashboard`

let mainVpnSessionActive = false
let wgTunnelReady = false
let tunnelApiActive = false
let tunnelApiBase = `http://${WG_TUNNEL_GATEWAY}:8000`
/** Bootstrap VPN на экране входа — API через main IPC (как Android tunnel). */
let bootstrapApiRouting = false

export function setMainVpnSessionActive(active: boolean) {
  mainVpnSessionActive = active
  if (!active) {
    wgTunnelReady = false
    tunnelApiActive = false
    return
  }
  // Renderer (Electron) не ходит на http://10.66.66.1 — API через main IPC.
  tunnelApiActive = false
}

export function setBootstrapApiRouting(active: boolean) {
  bootstrapApiRouting = active
}

export function isBootstrapApiRouting(): boolean {
  return bootstrapApiRouting
}

/** Main VPN или bootstrap — запросы через main IPC, не renderer xhr. */
export function shouldRouteApiViaMain(): boolean {
  return mainVpnSessionActive || bootstrapApiRouting
}

/** Всегда nip.io. С VPN на соте — через туннель; на Улье — hosts → 10.66.66.1. */
export function getAdminPanelUrl(_vpnConnected = false, _serverIp = ''): string {
  return PUBLIC_ADMIN_URL
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
