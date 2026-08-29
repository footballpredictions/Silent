const { execSync } = require('child_process')
const fs = require('fs')

const FALLBACK = '1.1.1.1,77.88.8.8'

function getLinuxSystemDns() {
  try {
    const out = execSync('resolvectl dns', { encoding: 'utf8', timeout: 4000 }).trim()
    const ips = [...out.matchAll(/\b(\d{1,3}(?:\.\d{1,3}){3})\b/g)].map(m => m[1])
    const uniq = [...new Set(ips.filter(ip => !ip.startsWith('127.')))]
    if (uniq.length) return uniq.slice(0, 4).join(',')
  } catch { /* ignore */ }
  try {
    const text = fs.readFileSync('/etc/resolv.conf', 'utf8')
    const ips = [...text.matchAll(/^nameserver\s+(\d{1,3}(?:\.\d{1,3}){3})/gm)].map(m => m[1])
    const uniq = [...new Set(ips.filter(ip => !ip.startsWith('127.')))]
    if (uniq.length) return uniq.slice(0, 4).join(',')
  } catch { /* ignore */ }
  return FALLBACK
}

function getSystemDns() {
  if (process.platform === 'linux') return getLinuxSystemDns()
  return getWindowsSystemDns()
}

/** DNS Windows для libclient (-sys-dns), как Android systemDnsForLibclient. */
function getWindowsSystemDns() {
  try {
    const ps = `
$addrs = Get-DnsClientServerAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
  ForEach-Object { $_.ServerAddresses } |
  Where-Object { $_ -match '^\\d+\\.\\d+\\.\\d+\\.\\d+$' } |
  Select-Object -Unique
($addrs | Select-Object -First 4) -join ','
`
    const out = execSync(
      `powershell.exe -NoProfile -Command "${ps.replace(/"/g, '\\"').replace(/\n/g, ' ')}"`,
      { encoding: 'utf8', timeout: 5000, windowsHide: true },
    ).trim()
    if (out && out.includes('.')) return out
  } catch { /* ignore */ }
  return FALLBACK
}

module.exports = { getWindowsSystemDns, getLinuxSystemDns, getSystemDns }
