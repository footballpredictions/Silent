const { execSync } = require('child_process')

const FALLBACK = '1.1.1.1,77.88.8.8'

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

module.exports = { getWindowsSystemDns }
