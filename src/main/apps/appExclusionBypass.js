/**
 * Реальный bypass для исключений приложений на Windows.
 *
 * 1) Сразу: префиксные наборы платформ (Steam/Epic/…) если выбран их .exe
 * 2) Постоянно: remote IP процессов (+ детей) → /32 через физ. шлюз
 */
const { execFile } = require('child_process')
const dns = require('dns').promises
const fs = require('fs')
const os = require('os')
const path = require('path')
const { promisify } = require('util')
const execFileAsync = promisify(execFile)

const {
  addServerBypassRoutes,
  removeHostBypassRoutes,
  capturePhysicalGateway,
} = require('../vpn/wireguard')
const { packsForExePaths, fetchSteamSdrCidrs } = require('./platformBypassPacks')

const IPV4_RE = /^\d{1,3}(?:\.\d{1,3}){3}$/
const POLL_MS = 700
const MAX_LEARNED = 400

let timer = null
let activeExePaths = []
let learnedTargets = new Set() // "ip" or "ip/prefix"
let packTargets = new Set()
let sendLog = null
let tickInFlight = false
let packsApplied = false

function normalizeExe(p) {
  return String(p || '')
    .trim()
    .replace(/\//g, '\\')
    .toLowerCase()
}

function isSkippableIp(ip) {
  if (!IPV4_RE.test(ip)) return true
  const p = ip.split('.').map(n => Number(n))
  if (p[0] === 127 || p[0] === 0 || p[0] >= 224) return true
  if (p[0] === 10) return true
  if (p[0] === 192 && p[1] === 168) return true
  if (p[0] === 172 && p[1] >= 16 && p[1] <= 31) return true
  if (p[0] === 169 && p[1] === 254) return true
  if (p[0] === 10 && p[1] === 66) return true
  return false
}

function buildCollectorScript(exePaths, outJsonPath) {
  const pathsLit = exePaths
    .map(p => `'${String(p).replace(/'/g, "''").toLowerCase()}'`)
    .join(', ')
  const outLit = String(outJsonPath).replace(/'/g, "''")
  return [
    '$ErrorActionPreference = "SilentlyContinue"',
    `$want = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)`,
    `$wantLeaf = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)`,
    `foreach ($p in @(${pathsLit})) {`,
    '  if (-not $p) { continue }',
    '  [void]$want.Add($p)',
    '  [void]$wantLeaf.Add([System.IO.Path]::GetFileName($p))',
    '}',
    'if ($want.Count -eq 0) { "[]" | Set-Content -LiteralPath \'' + outLit + '\' -Encoding UTF8; exit 0 }',
    '$pidSet = New-Object \'System.Collections.Generic.HashSet[int]\'',
    'Get-CimInstance Win32_Process | ForEach-Object {',
    '  $ep = [string]$_.ExecutablePath',
    '  $name = [string]$_.Name',
    '  $hit = $false',
    '  if ($ep -and $want.Contains($ep.ToLowerInvariant())) { $hit = $true }',
    '  elseif ($name -and $wantLeaf.Contains($name.ToLowerInvariant())) { $hit = $true }',
    '  if ($hit) { [void]$pidSet.Add([int]$_.ProcessId) }',
    '}',
    'if ($pidSet.Count -eq 0) { "[]" | Set-Content -LiteralPath \'' + outLit + '\' -Encoding UTF8; exit 0 }',
    '$parents = New-Object \'System.Collections.Generic.HashSet[int]\'',
    'foreach ($x in $pidSet) { [void]$parents.Add($x) }',
    'Get-CimInstance Win32_Process | ForEach-Object {',
    '  if ($parents.Contains([int]$_.ParentProcessId)) { [void]$pidSet.Add([int]$_.ProcessId) }',
    '}',
    '$ips = New-Object \'System.Collections.Generic.HashSet[string]\'',
    'Get-NetTCPConnection | ForEach-Object {',
    '  if (-not $pidSet.Contains([int]$_.OwningProcess)) { return }',
    '  $ra = [string]$_.RemoteAddress',
    '  if ($ra -match \'^\\d+\\.\\d+\\.\\d+\\.\\d+$\') { [void]$ips.Add($ra) }',
    '}',
    '$udp = & netstat.exe -ano -p UDP 2>$null',
    'foreach ($line in $udp) {',
    '  if ($line -notmatch \'UDP\') { continue }',
    '  $parts = ($line -split \'\\s+\') | Where-Object { $_ -ne \'\' }',
    '  if ($parts.Count -lt 4) { continue }',
    '  $pid = 0; [void][int]::TryParse($parts[$parts.Count-1], [ref]$pid)',
    '  if (-not $pidSet.Contains($pid)) { continue }',
    '  $foreign = $parts[2]',
    '  if ($foreign -match \'^(\\d+\\.\\d+\\.\\d+\\.\\d+):(\\d+)$\') {',
    '    if ($Matches[1] -ne \'0.0.0.0\' -and $Matches[1] -ne \'127.0.0.1\') { [void]$ips.Add($Matches[1]) }',
    '  }',
    '}',
    '$arr = @($ips)',
    '$json = ($arr | ConvertTo-Json -Compress)',
    'if ([string]::IsNullOrWhiteSpace($json)) { $json = \'[]\' }',
    `Set-Content -LiteralPath '${outLit}' -Value $json -Encoding UTF8`,
  ].join('\r\n')
}

async function collectRemoteIps(exePaths) {
  const list = [...new Set((exePaths || []).map(normalizeExe).filter(p => p.endsWith('.exe')))]
  if (!list.length) return []

  const stamp = `${Date.now()}-${process.pid}`
  const psPath = path.join(os.tmpdir(), `silent-excl-ips-${stamp}.ps1`)
  const jsonPath = path.join(os.tmpdir(), `silent-excl-ips-${stamp}.json`)
  try {
    fs.writeFileSync(psPath, '\uFEFF' + buildCollectorScript(list, jsonPath), 'utf8')
    await execFileAsync(
      'powershell.exe',
      ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', psPath],
      { windowsHide: true, timeout: 20000, maxBuffer: 4 * 1024 * 1024 },
    )
    if (!fs.existsSync(jsonPath)) return []
    let text = fs.readFileSync(jsonPath, 'utf8')
    if (text.charCodeAt(0) === 0xfeff) text = text.slice(1)
    text = text.trim()
    if (!text) return []
    const parsed = JSON.parse(text)
    const arr = Array.isArray(parsed) ? parsed : [parsed]
    return [...new Set(arr.map(String).filter(ip => !isSkippableIp(ip)))]
  } catch (e) {
    sendLog?.(`[Apps] bypass scan: ${e?.message || e}`)
    return []
  } finally {
    try { fs.unlinkSync(psPath) } catch { /* ignore */ }
    try { fs.unlinkSync(jsonPath) } catch { /* ignore */ }
  }
}

async function resolveHostsToIps(hosts) {
  const out = new Set()
  await Promise.all(
    (hosts || []).map(async (host) => {
      try {
        const addrs = await dns.resolve4(host)
        for (const ip of addrs) {
          if (!isSkippableIp(ip)) out.add(ip)
        }
      } catch { /* ignore */ }
    }),
  )
  return [...out]
}

async function applyPlatformPacks(exePaths) {
  const { packIds, cidrs, hosts, sdrAppIds } = packsForExePaths(exePaths)
  if (!packIds.length) {
    packsApplied = true
    return true
  }
  let sdrCidrs = []
  if (sdrAppIds?.length) {
    sdrCidrs = await fetchSteamSdrCidrs(sdrAppIds)
    if (sdrCidrs.length) {
      sendLog?.(`[Apps] Steam SDR: +${sdrCidrs.length} /24 (релеи задержки)`)
    }
  }
  const hostIps = await resolveHostsToIps(hosts)
  const targets = [...new Set([
    ...cidrs,
    ...sdrCidrs,
    ...hostIps.map(ip => `${ip}/32`),
  ])]
  if (!targets.length) {
    packsApplied = true
    return true
  }
  await capturePhysicalGateway(() => {})
  const ok = await addServerBypassRoutes(targets, sendLog, {
    quiet: false,
    label: `Apps/${packIds.join('+')}`,
  })
  if (ok) {
    for (const t of targets) packTargets.add(t)
    packsApplied = true
    sendLog?.(
      `[Apps] platform bypass: ${packIds.join(', ')} → ${targets.length} маршрутов (CIDR+DNS+SDR)`,
    )
    return true
  }
  // Не фиксируем packsApplied — tick/refresh повторят после шлюза/админа
  sendLog?.('[Apps] platform bypass не применился — нужен запуск от администратора', 'W')
  return false
}

async function tick() {
  if (tickInFlight || !activeExePaths.length) return
  tickInFlight = true
  try {
    if (!packsApplied) {
      await applyPlatformPacks(activeExePaths)
    }
    const ips = await collectRemoteIps(activeExePaths)
    const fresh = []
    for (const ip of ips) {
      const host = `${ip}/32`
      if (learnedTargets.has(host) || packTargets.has(host)) continue
      // /24 вокруг выученного IP — серверы игр часто рядом
      const parts = ip.split('.').map(Number)
      const net24 = `${parts[0]}.${parts[1]}.${parts[2]}.0/24`
      fresh.push(host)
      if (!learnedTargets.has(net24) && !packTargets.has(net24)) fresh.push(net24)
    }
    if (!fresh.length) return

    const room = Math.max(0, MAX_LEARNED - learnedTargets.size)
    const batch = [...new Set(fresh)].slice(0, Math.min(48, room))
    if (!batch.length) return

    await capturePhysicalGateway(() => {})
    const ok = await addServerBypassRoutes(batch, null, { quiet: true, label: 'Apps' })
    if (ok) {
      for (const t of batch) learnedTargets.add(t)
      sendLog?.(
        `[Apps] bypass +${batch.length} (всего ${learnedTargets.size + packTargets.size}) ← ${activeExePaths.map(p => path.basename(p)).join(', ')}`,
      )
    }
  } finally {
    tickInFlight = false
  }
}

function startAppExclusionBypass(exePaths, send) {
  sendLog = typeof send === 'function' ? send : null
  activeExePaths = [...new Set((exePaths || []).filter(p => /\.exe$/i.test(String(p || ''))))]
  packsApplied = false
  if (timer) {
    clearInterval(timer)
    timer = null
  }
  if (!activeExePaths.length) {
    sendLog?.('[Apps] bypass: нет .exe — монитор выкл')
    return
  }
  sendLog?.(
    `[Apps] bypass монитор: ${activeExePaths.length} exe — ${activeExePaths.map(p => path.basename(p)).join(', ')}`,
  )
  void tick()
  timer = setInterval(() => { void tick() }, POLL_MS)
}

/** После поднятия WG шлюз уже известен — сразу накатить platform packs. */
async function refreshAppExclusionBypassAfterTunnel(send) {
  if (send) sendLog = send
  if (!activeExePaths.length) {
    let paths = []
    try {
      const { getActiveExcludedExePaths } = require('./vpnAppExclusions')
      paths = getActiveExcludedExePaths()
    } catch { /* ignore */ }
    if (!paths.length) return
    startAppExclusionBypass(paths, send)
    return
  }
  packsApplied = false
  await applyPlatformPacks(activeExePaths)
  await tick()
}

async function stopAppExclusionBypass(send) {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
  activeExePaths = []
  packsApplied = false
  const ips = [...new Set([...learnedTargets, ...packTargets])]
  learnedTargets.clear()
  packTargets.clear()
  tickInFlight = false
  if (ips.length) {
    await removeHostBypassRoutes(ips, send || sendLog)
    ;(send || sendLog)?.(`[Apps] bypass снят: ${ips.length} маршрутов`)
  }
}

function getLearnedAppBypassIps() {
  return [...new Set([...learnedTargets, ...packTargets])]
}

module.exports = {
  startAppExclusionBypass,
  stopAppExclusionBypass,
  refreshAppExclusionBypassAfterTunnel,
  getLearnedAppBypassIps,
  collectRemoteIps,
  isSkippableIp,
}
