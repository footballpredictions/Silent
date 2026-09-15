'use strict'

/** Публичный IP Улья. В bypass только если он же WG/WDTT endpoint. */
const HIVE_PUBLIC_IP = '132.243.234.162'

function normalizePeerIp(raw, hiveIp = HIVE_PUBLIC_IP) {
  const s = String(raw || '').trim()
  if (/^\d{1,3}(\.\d{1,3}){3}$/.test(s)) return s
  return hiveIp
}

/**
 * Host-route bypass: peer (иначе UDP WG уходит в туннель) + VK (звонки/капча).
 * IP Улья не добавляем, если слот — сота: TCP 22/443 должны идти через VPN
 * (из РФ прямой TCP к Улью режется).
 */
function collectTunnelBypassIps({ serverIp, vkIps = [], hiveIp = HIVE_PUBLIC_IP } = {}) {
  const ips = new Set()
  const peer = normalizePeerIp(serverIp, hiveIp)
  if (peer) ips.add(peer)
  for (const ip of vkIps) {
    const s = String(ip || '').trim()
    if (/^\d{1,3}(\.\d{1,3}){3}$/.test(s)) ips.add(s)
  }
  return [...ips]
}

module.exports = {
  HIVE_PUBLIC_IP,
  normalizePeerIp,
  collectTunnelBypassIps,
}
