'use strict'

const RELEASES_JSON_URL = 'https://silentvpn3.github.io/releases.json'
const FETCH_TIMEOUT_MS = 8_000

function parseVersion(v) {
  const parts = String(v || '').match(/\d+/g)
  return parts && parts.length ? parts.map((n) => parseInt(n, 10) || 0) : [0]
}

function isNewer(latest, current) {
  const a = parseVersion(latest)
  const b = parseVersion(current)
  const n = Math.max(a.length, b.length)
  for (let i = 0; i < n; i++) {
    const da = a[i] || 0
    const db = b[i] || 0
    if (da !== db) return da > db
  }
  return false
}

function landingKey(platform) {
  const p = String(platform || '').trim().toLowerCase()
  if (p === 'android_tv' || p === 'tv') return 'android'
  if (p === 'macos' || p === 'darwin') return 'mac'
  if (p === 'windows' || p === 'win32') return 'pc'
  return p
}

function parseGithubOta(raw, platform, currentVersion, arch) {
  let root
  try {
    root = typeof raw === 'string' ? JSON.parse(raw) : raw
  } catch {
    return { kind: 'unreadable' }
  }
  if (!root || typeof root !== 'object') return { kind: 'unreadable' }
  const key = landingKey(platform)
  let row = root[key]
  if (!row || typeof row !== 'object') return { kind: 'unreadable' }
  if (key === 'mac' && row.arches && typeof row.arches === 'object') {
    const archKey = arch === 'arm64' ? 'arm64' : 'x64'
    const slot = row.arches[archKey]
    if (!slot || typeof slot !== 'object' || !slot.version || !slot.download_url) {
      return { kind: 'unreadable' }
    }
    row = { ...row, ...slot }
  }
  const version = String(row.version || '').trim()
  const filename = String(row.filename || '').trim()
  const downloadUrl = String(row.download_url || '').trim()
  if (!version || !filename || !/^https?:\/\//i.test(downloadUrl)) {
    return { kind: 'unreadable' }
  }
  if (!isNewer(version, currentVersion)) {
    return { kind: 'current', version }
  }
  return {
    kind: 'available',
    version,
    filename,
    size: Number(row.size) || 0,
    download_url: downloadUrl,
    github_download_url: downloadUrl,
    available: true,
  }
}

/** GitHub first. Hive/tunnel only if there is no GitHub URL at all. */
function otaDownloadCandidates({
  githubUrl,
  vpnUp,
  tunnelOrigin = 'http://10.66.66.1:8000',
  hiveDownloadPath = '/api/updates/download/pc',
} = {}) {
  const out = []
  const seen = new Set()
  const add = (raw) => {
    const v = String(raw || '').trim()
    if (!v || seen.has(v)) return
    seen.add(v)
    out.push(v)
  }
  add(githubUrl)
  if (!out.length && vpnUp) {
    const path = String(hiveDownloadPath || '').trim() || '/api/updates/download/pc'
    const norm = path.startsWith('/') ? path : `/${path}`
    add(`${String(tunnelOrigin || '').replace(/\/$/, '')}${norm}`)
  }
  return out
}

module.exports = {
  RELEASES_JSON_URL,
  FETCH_TIMEOUT_MS,
  isNewer,
  landingKey,
  parseGithubOta,
  otaDownloadCandidates,
}
