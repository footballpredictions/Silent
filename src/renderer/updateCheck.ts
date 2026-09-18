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
const RELEASES_JSON_URL = 'https://silentvpn3.github.io/releases.json'

function otaPlatformId(): string {
  if (typeof navigator === 'undefined') return 'pc'
  const ua = navigator.userAgent
  if (/linux/i.test(ua) && !/android/i.test(ua)) return 'linux'
  if (/mac os x|macintosh|darwin/i.test(ua)) return 'mac'
  return 'pc'
}

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
  const download = data.download_url || data.github_download_url || ''
  return {
    available: true,
    version: data.version,
    filename,
    size: data.size,
    uploaded_at: data.uploaded_at,
    download_url: download,
    github_download_url: data.github_download_url || download,
  }
}

async function checkViaGithubPages(): Promise<UpdateInfo | null> {
  try {
    const res = await axios.get(RELEASES_JSON_URL, {
      timeout: 8_000,
      params: { _: Date.now() },
    })
    const key = otaPlatformId()
    const row = res.data?.[key]
    if (!row?.version || !row?.download_url) {
      pushLog('Update', `github.io has no ${key} entry`, 'W')
      return null
    }
    return parseUpdateResponse({
      available: true,
      version: row.version,
      filename: row.filename,
      size: row.size,
      download_url: row.download_url,
      github_download_url: row.download_url,
    })
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    pushLog('Update', `github.io check fail: ${msg}`, 'W')
    return null
  }
}

export async function checkForUpdate(): Promise<UpdateInfo | null> {
  const electron = (window as typeof window & { electronAPI?: { checkForUpdate?: (v: string) => Promise<UpdateInfo | null> } }).electronAPI
  if (electron?.checkForUpdate) {
    try {
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
  return checkViaGithubPages()
}

export function getUpdateDownloadBase(): string {
  return getPublicApiBaseUrl()
}

export { APP_VERSION }
