/** IPv4 complement for site allowlists. Keep /0 and /1 tunnel/default routes untouched. */
function range(raw) {
  const m = String(raw).trim().match(/^(\d{1,3}(?:\.\d{1,3}){3})(?:\/(\d{1,2}))?$/)
  if (!m) return null
  const octets = m[1].split('.').map(Number)
  const prefix = m[2] == null ? 32 : Number(m[2])
  if (octets.some(n => n > 255) || prefix > 32) return null
  const ip = octets.reduce((n, octet) => n * 256 + octet, 0)
  const size = 2 ** (32 - prefix)
  const start = Math.floor(ip / size) * size
  return [start, start + size - 1]
}

function cidrs(start, end) {
  const out = []
  while (start <= end) {
    // /2 minimum: never replace an existing default route or a WG /1 route.
    let bits = 30
    while (bits > 0 && (start % (2 ** bits) !== 0 || start + 2 ** bits - 1 > end)) bits--
    const ip = [24, 16, 8, 0].map(shift => Math.floor(start / 2 ** shift) % 256).join('.')
    out.push(`${ip}/${32 - bits}`)
    start += 2 ** bits
  }
  return out
}

function siteDirectTargets(targets, whitelist = false, dnsServers = []) {
  if (!whitelist) return targets
  // DNS and the in-tunnel API remain reachable even with an empty site allowlist.
  const ranges = [...targets, '10.66.66.0/24', ...dnsServers]
    .map(range).filter(Boolean).sort((a, b) => a[0] - b[0])
  const out = []
  let cursor = 0
  for (const [start, end] of ranges) {
    if (cursor < start) out.push(...cidrs(cursor, start - 1))
    cursor = Math.max(cursor, end + 1)
  }
  if (cursor < 2 ** 32) out.push(...cidrs(cursor, 2 ** 32 - 1))
  return out
}

module.exports = { siteDirectTargets }
