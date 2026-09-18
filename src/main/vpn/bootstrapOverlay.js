'use strict'

const HIVE_IP = '89.125.188.100'
const HIVE_HOST = '89-125-188-100.nip.io'
const AI_EXIT_IPS = new Set(['192.177.26.38'])
const DEFAULT_WDTT_PORT = 56000

function hostOf(raw) {
  const s = String(raw || '').trim()
  if (!s) return ''
  try {
    const u = new URL(/:\/\//.test(s) ? s : `http://${s}`)
    return String(u.hostname || '').replace(/\.$/, '')
  } catch {
    return ''
  }
}

function cellIpsFromUrls(urls, hiveIps = [HIVE_IP, HIVE_HOST], skipIps = [...AI_EXIT_IPS]) {
  const hive = new Set([...hiveIps].map((x) => String(x).trim().toLowerCase()).filter(Boolean))
  const skip = new Set([...skipIps].map((x) => String(x).trim().toLowerCase()))
  const out = []
  const seen = new Set()
  for (const raw of urls || []) {
    const host = hostOf(raw).toLowerCase()
    if (!host || hive.has(host) || skip.has(host)) continue
    if (!/^\d+\.\d+\.\d+\.\d+$/.test(host)) continue
    if (seen.has(host)) continue
    seen.add(host)
    out.push(host)
  }
  return out
}

function pickBootstrapOverlay({
  hiveIp = HIVE_IP,
  hivePort = DEFAULT_WDTT_PORT,
  cellIps = [],
  cellPort = DEFAULT_WDTT_PORT,
} = {}) {
  const hive = String(hiveIp || '').trim()
  const cell = (cellIps || []).map((x) => String(x || '').trim()).find((x) => x && x !== hive)
  if (cell) return { ip: cell, port: cellPort, isHive: false }
  return { ip: hive, port: hivePort, isHive: true }
}

function isHiveBootstrapIp(ip, hiveIp = HIVE_IP) {
  const got = String(ip || '').trim()
  return !got || got === String(hiveIp || '').trim()
}

module.exports = {
  HIVE_IP,
  DEFAULT_WDTT_PORT,
  cellIpsFromUrls,
  pickBootstrapOverlay,
  isHiveBootstrapIp,
}
