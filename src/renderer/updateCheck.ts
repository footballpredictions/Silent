import axios from 'axios'

import { getPublicApiBaseUrl } from './api'
import { pushLog } from './debugLog'

export interface UpdateInfo {
  available: boolean
  version?: string
  filename?: string
  size?: number
  uploaded_at?: string
  download_url?: string
  github_download_url?: string
  tunnel_download_url?: string
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
    download_url: data.download_url || data.github_download_url || `/update/pc/${encodeURIComponent(filename)}`,
    github_download_url: data.github_download_url,
    tunnel_download_url: data.tunnel_download_url || '/api/updates/download/pc',
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
    pushLog('Update', `check fail: ${msg}`, 'W')
    return null
  }
}

export async function checkForUpdate(): Promise<UpdateInfo | null> {
  const electron = (window as typeof window & { electronAPI?: { checkForUpdate?: (v: string) => Promise<UpdateInfo | null> } }).electronAPI
  if (electron?.checkForUpdate) {
    try {
      // null = обновлений нет или check вернул пусто — НЕ ходим в public axios
      // (при VPN это даёт ложный «Network Error»).
      const data = await electron.checkForUpdate(APP_VERSION)
      return parseUpdateResponse(data)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      if (!/CAPTCHA_BUSY|paused during captcha/i.test(msg)) {
        pushLog('Update', `check fail: ${msg}`, 'W')
      }
      return null
    }
  }
  return checkViaRendererPublic()
}

export function getUpdateDownloadBase(): string {
  return getPublicApiBaseUrl()
}

export { APP_VERSION }
