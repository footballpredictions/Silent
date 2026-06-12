import type { VpnConfigPayload } from './vkConfig'

/** Локальный bootstrap без HTTPS к бекенду (как Android BootstrapVpnConfig). */
const SERVER_HOST = '132.243.234.162'
const SERVER_PORT = 56000
const WDTT_MASTER_PASSWORD = 'hAKfvX0lUTNuXJueD9Zx'
const DEFAULT_SERVER_URL = 'https://132-243-234-162.nip.io'

function serverHost(): string {
  try {
    const host = new URL(DEFAULT_SERVER_URL).hostname
    return host || SERVER_HOST
  } catch {
    return SERVER_HOST
  }
}

export function buildLocalBootstrapConfig(vkHash: string, preLoginFingerprint: string): VpnConfigPayload {
  const fp = preLoginFingerprint.trim()
  return {
    device_id: `boot:${fp}`,
    wg_private_key: '',
    assigned_ip: '',
    server_public_key: '',
    server_ip: SERVER_HOST,
    server_port: SERVER_PORT,
    dns: '1.1.1.1, 1.0.0.1, 77.88.8.8',
    wdtt_password: WDTT_MASTER_PASSWORD,
    vk_hashes: [vkHash],
    stream_count: 3,
  }
}
