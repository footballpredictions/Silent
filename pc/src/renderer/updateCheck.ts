import api from './api'

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

export async function checkForUpdate(): Promise<UpdateInfo | null> {
  try {
    const res = await api.get<UpdateInfo>('/api/updates/check', {
      params: { platform: 'pc', version: APP_VERSION },
      timeout: 20_000,
    })
    if (res.data?.available) return res.data
    return null
  } catch {
    return null
  }
}

export { APP_VERSION }
