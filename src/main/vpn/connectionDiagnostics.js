const { execFile } = require('node:child_process')
const { promisify } = require('node:util')

// Query only. Return booleans so the diagnostic log contains no adapter names,
// connection names, addresses, or DNS provider details.
const WINDOWS_PROBE = String.raw`
$ErrorActionPreference = 'SilentlyContinue'
$services = @(Get-Service | Where-Object { $_.Status -eq 'Running' -and $_.Name -like 'WireGuardTunnel$*' })
$silentService = 'WireGuardTunnel$wg-turn'
$adapters = @(Get-NetAdapter | Where-Object { $_.Status -eq 'Up' })
$vpnAdapter = $adapters | Where-Object {
    $_.Name -ne 'wg-turn' -and
    $_.InterfaceDescription -match 'WireGuard Tunnel|OpenVPN|TAP-Windows|Tailscale|ZeroTier|Cloudflare WARP|NordLynx|AnyConnect|Fortinet.*VPN'
} | Select-Object -First 1
$ras = @(
    Get-VpnConnection
    Get-VpnConnection -AllUserConnection
) | Where-Object {
    $_.ConnectionStatus -eq 'Connected'
} | Select-Object -First 1
$dohConfigured = $false
if (Get-Command Get-DnsClientDohServerAddress) {
    $defaultIndices = @((Get-NetRoute -DestinationPrefix '0.0.0.0/0').InterfaceIndex) +
        @((Get-NetRoute -DestinationPrefix '::/0').InterfaceIndex)
    $uplinks = @($adapters | Where-Object {
        $_.HardwareInterface -and $_.ifIndex -in $defaultIndices
    })
    if ($uplinks.Count -gt 0) {
        $dns = (Get-DnsClientServerAddress -InterfaceIndex $uplinks.ifIndex).ServerAddresses
        $dohConfigured = [bool](Get-DnsClientDohServerAddress | Where-Object {
            $_.AutoUpgrade -and $_.ServerAddress -in $dns
        } | Select-Object -First 1)
    }
}
[pscustomobject]@{
    otherVpn = [bool]($vpnAdapter -or $ras -or ($services | Where-Object { $_.Name -ne $silentService }))
    silentServiceRunning = [bool]($services | Where-Object { $_.Name -eq $silentService })
    dohConfigured = $dohConfigured
} | ConvertTo-Json -Compress
`

async function getWindowsConnectionHints({ wireGuardApplied, run = promisify(execFile) }) {
  try {
    const command = Buffer.from(WINDOWS_PROBE, 'utf16le').toString('base64')
    const { stdout } = await run('powershell.exe', [
      '-NoProfile', '-NonInteractive', '-EncodedCommand', command,
    ], { windowsHide: true, timeout: 7000, maxBuffer: 16 * 1024 })
    const state = JSON.parse(stdout)
    const hints = []
    if (state.otherVpn === true) {
      hints.push('Обнаружено другое VPN-подключение, активный адаптер или служба. Проверьте, не мешает ли оно Silent VPN.')
    }
    if (state.silentServiceRunning === true && !wireGuardApplied) {
      hints.push('Служба WireGuardTunnel$wg-turn запущена, а готовность WireGuard не подтверждена. Возможен остаток предыдущей сессии.')
    }
    if (state.dohConfigured === true) {
      hints.push('На основном сетевом адаптере настроен системный DNS-over-HTTPS. Если домены не открываются, проверьте доступность DNS-сервера.')
    }
    return hints
  } catch {
    return []
  }
}

module.exports = { getWindowsConnectionHints }
