import type { VpnConfigPayload } from './vkConfig'
import { getCachedTheme } from './themeStore'
import { standbyApiBasesFromTheme } from './clientTheme'

/** Локальный bootstrap без HTTPS к бекенду (как Android BootstrapVpnConfig). */
const SERVER_HOST = '89.125.188.100'
const SERVER_PORT = 56000
const WDTT_MASTER_PASSWORD = 'hAKfvX0lUTNuXJueD9Zx'
const BAKED_CELLS = ['http://87.58.213.193:9100', 'http://78.17.74.27:9100']
const AI_EXIT = new Set(['192.177.26.38'])

function hostOf(raw: string): string {
  const s = String(raw || '').trim()
  if (!s) return ''
  try {
    return new URL(/:\/\//.test(s) ? s : `http://${s}`).hostname.replace(/\.$/, '')
  } catch {
    return ''
  }
}

export function cellIpsFromUrls(urls: string[]): string[] {
  const hive = new Set(['89.125.188.100', '89-125-188-100.nip.io'])
  const out: string[] = []
  const seen = new Set<string>()
  for (const raw of urls) {
    const host = hostOf(raw).toLowerCase()
    if (!host || hive.has(host) || AI_EXIT.has(host)) continue
    if (!/^\d+\.\d+\.\d+\.\d+$/.test(host)) continue
    if (seen.has(host)) continue
    seen.add(host)
    out.push(host)
  }
  return out
}

export function pickBootstrapOverlay(cellIps: string[], hiveIp = SERVER_HOST, hivePort = SERVER_PORT) {
  const cell = cellIps.map((x) => x.trim()).find((x) => x && x !== hiveIp)
  if (cell) return { ip: cell, port: hivePort, isHive: false as const }
  return { ip: hiveIp, port: hivePort, isHive: true as const }
}

export function buildLocalBootstrapConfig(vkHash: string, preLoginFingerprint: string): VpnConfigPayload {
  const fp = preLoginFingerprint.trim()
  const urls = [...standbyApiBasesFromTheme(getCachedTheme()), ...BAKED_CELLS]
  const overlay = pickBootstrapOverlay(cellIpsFromUrls(urls), SERVER_HOST, SERVER_PORT)
  return {
    device_id: `boot:${fp}`,
    wg_private_key: '',
    assigned_ip: '',
    server_public_key: '',
    server_ip: overlay.ip,
    server_port: overlay.port,
    dns: '1.1.1.1, 1.0.0.1, 77.88.8.8',
    wdtt_password: WDTT_MASTER_PASSWORD,
    vk_hashes: [vkHash],
    stream_count: 3,
  }
}
