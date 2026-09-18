'use strict'

const fs = require('fs')
const path = require('path')
const { execFile } = require('child_process')

const HIVE_IP = '89.125.188.100'
const ADMIN_NIP_HOST = '89-125-188-100.nip.io'
const ADMIN_PANEL_URL = `https://${ADMIN_NIP_HOST}/dashboard`
const TUNNEL_GW = '10.66.66.1'
const HOSTS_MARKER = 'silent-vpn-admin-nip'

function peerIsHive(serverIp, hiveIp = HIVE_IP) {
  const s = String(serverIp || '').trim()
  return !s || s === hiveIp
}

/** На соте IP Улья должен идти через WG, иначе nip.io:443 с РФ таймаутит. */
function bypassWithoutHiveIfCell(excludeIPs, serverIp, hiveIp = HIVE_IP) {
  const list = [...(excludeIPs || [])]
  if (peerIsHive(serverIp, hiveIp)) return list
  return list.filter((ip) => ip !== hiveIp)
}

/** Всегда публичный nip.io. С VPN трафик идёт через туннель (сота) или hosts-pin на Улье. */
function resolveAdminPanelUrl() {
  return ADMIN_PANEL_URL
}

function isHivePublicUrl(url) {
  return /89-125-188-100\.nip\.io|89\.125\.188\.100/i.test(String(url || ''))
}

/** Оплата в системном браузере — мимо WG. Админка/nip.io сюда не входят. */
function isPaymentBrowserUrl(url) {
  return /yoomoney\.ru|money\.yandex\.ru|sberbank\.ru|sber\.ru|sberid\.ru/i.test(String(url || ''))
}

function applyAdminNipPin(hostsText, { pin, ip = TUNNEL_GW, host = ADMIN_NIP_HOST } = {}) {
  const nl = String(hostsText || '').includes('\r\n') ? '\r\n' : '\n'
  const lines = String(hostsText || '').split(/\r?\n/).filter((line) => !line.includes(HOSTS_MARKER))
  while (lines.length && lines[lines.length - 1] === '') lines.pop()
  if (pin) lines.push(`${ip} ${host} # ${HOSTS_MARKER}`)
  return `${lines.join(nl)}${nl}`
}

function windowsHostsPath() {
  if (process.platform !== 'win32') return '/etc/hosts'
  return path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'drivers', 'etc', 'hosts')
}

function syncAdminNipHosts(pin, send) {
  try {
    const file = windowsHostsPath()
    const raw = fs.readFileSync(file, 'utf8')
    const next = applyAdminNipPin(raw, { pin: !!pin })
    if (next !== raw) fs.writeFileSync(file, next)
    if (process.platform === 'win32') {
      execFile('ipconfig', ['/flushdns'], { windowsHide: true }, () => {})
    }
    send?.(`[Admin] hosts nip.io ${pin ? `→ ${TUNNEL_GW}` : 'снят'}`)
    return true
  } catch (e) {
    send?.(`[Admin] hosts nip.io: ${e?.message || e}`)
    return false
  }
}

module.exports = {
  HIVE_IP,
  ADMIN_NIP_HOST,
  ADMIN_PANEL_URL,
  TUNNEL_GW,
  peerIsHive,
  bypassWithoutHiveIfCell,
  resolveAdminPanelUrl,
  isHivePublicUrl,
  isPaymentBrowserUrl,
  applyAdminNipPin,
  syncAdminNipHosts,
}
