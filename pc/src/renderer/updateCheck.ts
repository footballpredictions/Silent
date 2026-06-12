import axios from 'axios'

import api, { getPublicApiBaseUrl } from './api'
import { pushLog } from './debugLog'
import { isTunnelApiActive } from './tunnelApi'

export interface UpdateInfo {
  available: boolean
  version?: string
  filename?: string
  size?: number
  uploaded_at?: string
  download_url?: string
}

const APP_VERSION = __APP_VERSION__

export function getAppVersion(): string {
  return APP_VERSION
}

export function compareVersions(a: string, b: string): number {
  const pa = a.split('.').map(n => parseInt(n, 10) || 0)
  const pb = b.split('.').map(n => parseInt(n, 10) || 0)
  const len = Math.max(pa.length, pb.length)
  for (let i = 0; i < len; i++) {
    const da = pa[i] ?? 0
    const db = pb[i] ?? 0
    if (da > db) return 1
    if (da < db) return -1
  }
  return 0
}

function parseUpdateResponse(data: UpdateInfo | null | undefined): UpdateInfo | null {
  if (!data?.version) return null
  if (compareVersions(data.version, APP_VERSION) <= 0) return null
  pushLog('Update', `available ${APP_VERSION} → ${data.version}`)
  const filename = data.filename || ''
  return {
    available: true,
    version: data.version,
    filename,
    size: data.size,
    uploaded_at: data.uploaded_at,
    download_url: data.download_url || `/update/pc/${encodeURIComponent(filename)}`,
  }
}

async function checkViaTunnel(): Promise<UpdateInfo | null> {
  if (!isTunnelApiActive()) return null
  try {
    const res = await api.get<UpdateInfo>('/api/updates/check', {
      params: { platform: 'pc', version: APP_VERSION },
      timeout: 45_000,
    })
    return parseUpdateResponse(res.data)
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    pushLog('Update', `tunnel check fail: ${msg}`, 'W')
    return null
  }
}

async function checkViaRendererPublic(): Promise<UpdateInfo | null> {
  const base = getPublicApiBaseUrl()
  try {
    const res = await axios.get<UpdateInfo>(`${base}/api/updates/check`, {
      params: { platform: 'pc', version: APP_VERSION },
      timeout: 45_000,
    })
    return parseUpdateResponse(res.data)
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    pushLog('Update', `public check fail (${base}): ${msg}`, 'W')
    return null
  }
}

/** OTA: main process HTTPS → tunnel (если VPN) → renderer public. */
export async function checkForUpdate(): Promise<UpdateInfo | null> {
  const electron = (window as typeof window & { electronAPI?: { checkForUpdate?: (v: string) => Promise<UpdateInfo | null> } }).electronAPI
  if (electron?.checkForUpdate) {
    try {
      const data = await electron.checkForUpdate(APP_VERSION)
      const parsed = parseUpdateResponse(data)
      if (parsed) return parsed
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      pushLog('Update', `main check fail: ${msg}`, 'W')
    }
  }
  const viaTunnel = await checkViaTunnel()
  if (viaTunnel) return viaTunnel
  return checkViaRendererPublic()
}

export { APP_VERSION }
