import axios from 'axios'

import { getServerUrl } from './api'

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

/** OTA — только public HTTPS, без tunnel API. */
export async function checkForUpdate(): Promise<UpdateInfo | null> {
  for (const base of publicUpdateBases()) {
    try {
      const res = await axios.get<UpdateInfo>(`${base}/api/updates/check`, {
        params: { platform: 'pc', version: APP_VERSION },
        timeout: 20_000,
      })
      if (res.data?.available) return res.data
    } catch {
      /* try next base */
    }
  }
  return null
}

export { APP_VERSION }
