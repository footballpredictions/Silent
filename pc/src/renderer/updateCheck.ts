import axios from 'axios'

import { getServerUrl } from './api'
import { pushLog } from './debugLog'

export interface UpdateInfo {
  available: boolean
  version?: string
  filename?: string
  size?: number
  uploaded_at?: string
  download_url?: string
}

const APP_VERSION = __APP_VERSION__
const FALLBACK_PUBLIC_URL = 'https://132-243-234-162.nip.io'

export function getAppVersion(): string {
  return APP_VERSION
}

function publicUpdateBases(): string[] {
  const primary = (getServerUrl() || FALLBACK_PUBLIC_URL).replace(/\/$/, '')
  const nip = FALLBACK_PUBLIC_URL.replace(/\/$/, '')
  return primary === nip ? [primary] : [primary, nip]
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

/** OTA — только public HTTPS, без tunnel API. */
export async function checkForUpdate(): Promise<UpdateInfo | null> {
  for (const base of publicUpdateBases()) {
    try {
      const res = await axios.get<UpdateInfo>(`${base}/api/updates/check`, {
        params: { platform: 'pc', version: APP_VERSION },
        timeout: 20_000,
      })
      const data = res.data
      if (!data?.version) continue
      if (compareVersions(data.version, APP_VERSION) <= 0) continue
      pushLog('Update', `available ${APP_VERSION} → ${data.version}`)
      return {
        available: true,
        version: data.version,
        filename: data.filename,
        size: data.size,
        uploaded_at: data.uploaded_at,
        download_url: data.download_url || `/update/pc/${encodeURIComponent(data.filename || '')}`,
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      pushLog('Update', `check fail (${base}): ${msg}`, 'W')
    }
  }
  return null
}

export { APP_VERSION }
