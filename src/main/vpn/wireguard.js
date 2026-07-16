/**
 * WireGuard Windows: wireguard.exe + wintun.dll bundled в PC-клиенте (resources/wireguard/).
 * Устанавливает службу WireGuardTunnel$wg-turn через /installtunnelservice.
 */
const path = require('path')
const fs = require('fs')
const os = require('os')
const net = require('net')
const { exec, execSync, execFile, execFileSync, spawn } = require('child_process')
const { promisify } = require('util')
const execAsync = promisify(exec)
const execFileAsync = promisify(execFile)

const TUNNEL_NAME = 'wg-turn'
const TUNNEL_CONF_NAME = 'wg-turn.conf'
const SERVICE_NAME = `WireGuardTunnel$${TUNNEL_NAME}`
const STABLE_CONF_DIR = path.join(process.env.ProgramData || 'C:\\ProgramData', 'SilentVPN')
const STABLE_WG_DIR = path.join(STABLE_CONF_DIR, 'wireguard')
const FALLBACK_BACKEND_IP = '132.243.234.162'
/** DNS: Cloudflare+Yandex по умолчанию. Debug override — через options/config.dns_override. */
const WG_DNS = '1.1.1.1, 1.0.0.1, 77.88.8.8'

function pickDnsServers(value) {
  return String(value || '')
    .split(/[,;\s]+/)
    .map(s => s.trim())
    .filter(Boolean)
    .join(', ')
}

function normalizeDnsValue(raw, override) {
  const fromOverride = pickDnsServers(override)
  if (fromOverride) return fromOverride
  return WG_DNS
}

let lastRuntimeDir = null
/** Физический шлюз до установки WG — для bypass API/админки при full tunnel. */
let savedPhysicalGateway = null
/** Сериализация stop/install — disconnect в фоне не гоняется с новым connect. */
let wgStopChain = Promise.resolve()

function enqueueWgStop(fn) {
  const next = wgStopChain.then(fn, fn)
  wgStopChain = next.catch(() => {})
  return next
}

/** Дождаться завершения фонового stop (disconnect) перед новым install. */
function waitWgStopIdle() {
  return wgStopChain
}

function resourcesDir(isDev, dirname) {
  return isDev ? path.join(dirname, '../../resources') : process.resourcesPath
}

const SYSTEM_WG_DIR = 'C:\\Program Files\\WireGuard'

function findBundledDir(isDev, dirname) {
  const base = resourcesDir(isDev, dirname)
  const candidates = [
    path.join(base, 'wireguard'),
    base,
  ]
  for (const dir of candidates) {
    if (fs.existsSync(path.join(dir, 'wireguard.exe'))) return dir
  }
  return null
}

function findWintunDll(dir) {
  if (!dir) return null
  const p = path.join(dir, 'wintun.dll')
  return fs.existsSync(p) ? p : null
}

function wgExeVersion(dir) {
  const exe = path.join(dir || '', 'wireguard.exe')
  if (!fs.existsSync(exe)) return '0'
  try {
    const out = execSync(
      `powershell.exe -NoProfile -Command "(Get-Item -LiteralPath '${exe.replace(/'/g, "''")}').VersionInfo.ProductVersion"`,
      { encoding: 'utf8', windowsHide: true, timeout: 5000 },
    )
    return String(out || '').trim() || '0'
  } catch {
    return '0'
  }
}

/** semver-ish: "1.1" > "1.0.1" > "0.5.3" */
function cmpVersion(a, b) {
  const pa = String(a || '0').split(/[^\d]+/).filter(Boolean).map(n => parseInt(n, 10) || 0)
  const pb = String(b || '0').split(/[^\d]+/).filter(Boolean).map(n => parseInt(n, 10) || 0)
  const n = Math.max(pa.length, pb.length)
  for (let i = 0; i < n; i++) {
    const d = (pa[i] || 0) - (pb[i] || 0)
    if (d) return d
  }
  return 0
}

function pickBestWgSource(isDev, dirname, send) {
  const candidates = []
  const bundled = findBundledDir(isDev, dirname)
  if (bundled) candidates.push({ dir: bundled, label: 'bundled' })
  if (fs.existsSync(path.join(SYSTEM_WG_DIR, 'wireguard.exe'))) {
    candidates.push({ dir: SYSTEM_WG_DIR, label: 'Program Files' })
  }
  // ProgramData — только цель копирования, не источник (залипает 0.5.3 / wintun.dll).
  let best = null
  for (const c of candidates) {
    const ver = wgExeVersion(c.dir)
    if (!best || cmpVersion(ver, best.ver) > 0) {
      best = { ...c, ver }
    }
  }
  if (best) send?.(`[WG] WireGuard ${best.ver} ← ${best.label} (${best.dir})`)
  return best
}

let elevatedCache = { at: 0, value: false }

function isProcessElevated() {
  const now = Date.now()
  if (now - elevatedCache.at < 60_000) return elevatedCache.value
  try {
    execSync('net session', { stdio: 'ignore', windowsHide: true, timeout: 3000 })
    elevatedCache = { at: now, value: true }
    return true
  } catch {
    elevatedCache = { at: now, value: false }
    return false
  }
}

/**
 * WireGuardNT 1.x + wintun.dll в той же папке → служба падает SCM 7024.
 * wintun нужен только для legacy < 1.0.
 */
function cleanupLegacyWintun(dir, wgVer, send) {
  if (!dir || cmpVersion(wgVer, '1.0') < 0) return
  const wintun = path.join(dir, 'wintun.dll')
  if (!fs.existsSync(wintun)) return
  try {
    fs.unlinkSync(wintun)
    send?.('[WG] Удалён wintun.dll (WireGuardNT 1.x, иначе SCM 7024)')
  } catch (e) {
    send?.(`[WG] wintun.dll не удалить: ${e.message} — переключимся на Program Files`)
  }
}

/**
 * Если ProgramData залип на старом 0.5.3 (служба держит файл) —
 * снять службу и перезаписать бинарники с best (как делает установщик).
 */
function forceRefreshProgramDataFrom(best, send) {
  if (!best?.dir || !isProcessElevated()) return false
  const stableVer = wgExeVersion(STABLE_WG_DIR)
  if (!(cmpVersion(best.ver, stableVer) > 0)) return false

  send?.(`[WG] ProgramData ${stableVer} устарел → ${best.ver}, сбрасываю службу…`)
  const tryExe = [
    path.join(SYSTEM_WG_DIR, 'wireguard.exe'),
    path.join(best.dir, 'wireguard.exe'),
    path.join(STABLE_WG_DIR, 'wireguard.exe'),
  ]
  for (const exe of tryExe) {
    if (!fs.existsSync(exe)) continue
    try {
      runCmd(`"${exe}" /uninstalltunnelservice ${TUNNEL_NAME}`, path.dirname(exe))
    } catch { /* ignore */ }
  }
  runCmd(`sc stop "${SERVICE_NAME}"`)
  runCmd(`sc delete "${SERVICE_NAME}"`)

  fs.mkdirSync(STABLE_WG_DIR, { recursive: true })
  let copied = false
  for (const name of ['wireguard.exe', 'wg.exe']) {
    const src = path.join(best.dir, name)
    const dest = path.join(STABLE_WG_DIR, name)
    if (!fs.existsSync(src)) continue
    try {
      fs.copyFileSync(src, dest)
      copied = true
    } catch (e) {
      send?.(`[WG] refresh ${name}: ${e.message}`)
    }
  }
  if (copied) {
    cleanupLegacyWintun(STABLE_WG_DIR, best.ver, send)
    send?.(`[WG] ProgramData обновлён до ${wgExeVersion(STABLE_WG_DIR)}`)
  }
  return copied
}

/**
 * Runtime для службы: актуальный wireguard.exe (1.1+ / WireGuardNT).
 * wintun.dll опционален (с 1.0 драйвер WireGuardNT, не Wintun).
 * Не залипаем на старом ProgramData 0.5.3 при reuse.
 */
function prepareRuntimeDir(isDev, dirname, send, options = {}) {
  const best = pickBestWgSource(isDev, dirname, send)
  if (!best) {
    send?.('[WG] Не найден wireguard.exe (resources/wireguard или Program Files\\WireGuard)')
    return null
  }

  forceRefreshProgramDataFrom(best, send)

  const stableVer = wgExeVersion(STABLE_WG_DIR)
  const reuse = options.reuse === true
    && fs.existsSync(path.join(STABLE_WG_DIR, 'wireguard.exe'))
    && cmpVersion(stableVer, best.ver) >= 0
    && !fs.existsSync(path.join(STABLE_WG_DIR, 'wintun.dll'))

  if (reuse) {
    cleanupLegacyWintun(STABLE_WG_DIR, stableVer, send)
    lastRuntimeDir = STABLE_WG_DIR
    send?.(`[WG] Runtime: ${STABLE_WG_DIR} (reuse ${stableVer})`)
    return STABLE_WG_DIR
  }

  // Program Files уже лучший и стабильный путь — служба может ссылаться туда напрямую.
  if (best.dir === SYSTEM_WG_DIR) {
    cleanupLegacyWintun(STABLE_WG_DIR, best.ver, send)
    lastRuntimeDir = SYSTEM_WG_DIR
    send?.(`[WG] Runtime: ${SYSTEM_WG_DIR} (system ${best.ver})`)
    return SYSTEM_WG_DIR
  }

  fs.mkdirSync(STABLE_WG_DIR, { recursive: true })
  for (const name of ['wireguard.exe', 'wg.exe']) {
    const src = path.join(best.dir, name)
    const dest = path.join(STABLE_WG_DIR, name)
    if (!fs.existsSync(src)) continue
    try {
      fs.copyFileSync(src, dest)
    } catch (e) {
      if (e.code === 'EBUSY' && fs.existsSync(dest)) {
        // Если в ProgramData старая версия и занята — лучше system, если есть.
        if (fs.existsSync(path.join(SYSTEM_WG_DIR, 'wireguard.exe'))
          && cmpVersion(wgExeVersion(SYSTEM_WG_DIR), stableVer) > 0) {
          lastRuntimeDir = SYSTEM_WG_DIR
          send?.(`[WG] ${name} занят — переключаемся на Program Files`)
          return SYSTEM_WG_DIR
        }
        send?.(`[WG] ${name} занят службой — используем ${dest}`)
      } else if (fs.existsSync(dest)) {
        send?.(`[WG] ${name}: ${e.message} — используем существующий`)
      } else if (fs.existsSync(path.join(SYSTEM_WG_DIR, 'wireguard.exe'))) {
        lastRuntimeDir = SYSTEM_WG_DIR
        send?.(`[WG] Не удалось скопировать ${name} — Program Files`)
        return SYSTEM_WG_DIR
      } else {
        throw e
      }
    }
  }

  cleanupLegacyWintun(STABLE_WG_DIR, best.ver, send)

  const wintunSrc = findWintunDll(best.dir)
  if (wintunSrc && cmpVersion(best.ver, '1.0') < 0) {
    const wintunDest = path.join(STABLE_WG_DIR, 'wintun.dll')
    try {
      fs.copyFileSync(wintunSrc, wintunDest)
    } catch (e) {
      if (!(e.code === 'EBUSY' && fs.existsSync(wintunDest))) {
        send?.(`[WG] wintun.dll: ${e.message}`)
      }
    }
  } else if (cmpVersion(best.ver, '1.0') >= 0) {
    cleanupLegacyWintun(STABLE_WG_DIR, best.ver, send)
  }

  const copiedVer = wgExeVersion(STABLE_WG_DIR)
  if (cmpVersion(copiedVer, best.ver) < 0) {
    if (fs.existsSync(path.join(SYSTEM_WG_DIR, 'wireguard.exe'))) {
      lastRuntimeDir = SYSTEM_WG_DIR
      send?.(`[WG] ProgramData ${copiedVer} < ${best.ver} — Program Files`)
      return SYSTEM_WG_DIR
    }
    lastRuntimeDir = best.dir
    send?.(`[WG] ProgramData не обновлён — runtime ${best.dir}`)
    return best.dir
  }

  if (cmpVersion(best.ver, copiedVer) > 0 && fs.existsSync(path.join(SYSTEM_WG_DIR, 'wireguard.exe'))) {
    lastRuntimeDir = SYSTEM_WG_DIR
    send?.(`[WG] ProgramData остался ${copiedVer}, берём system ${best.ver}`)
    return SYSTEM_WG_DIR
  }

  lastRuntimeDir = STABLE_WG_DIR
  send?.(`[WG] Runtime: ${STABLE_WG_DIR} (${copiedVer})`)
  return STABLE_WG_DIR
}

function runCmd(cmd, cwd) {
  try {
    return execSync(cmd, { cwd, encoding: 'utf8', windowsHide: true, timeout: 45000, stdio: 'pipe' })
  } catch (e) {
    const out = [e.stdout, e.stderr, e.message].filter(Boolean).join('\n').trim()
    return out || null
  }
}

/** Async — не блокирует Electron main (иначе UI «Не отвечает» при bootstrap). */
async function runCmdAsync(cmd, cwd, timeoutMs = 45000) {
  try {
    const { stdout, stderr } = await execAsync(cmd, {
      cwd,
      encoding: 'utf8',
      windowsHide: true,
      timeout: timeoutMs,
      maxBuffer: 2 * 1024 * 1024,
    })
    return [stdout, stderr].filter(Boolean).join('\n').trim() || null
  } catch (e) {
    const out = [e.stdout, e.stderr, e.message].filter(Boolean).join('\n').trim()
    return out || null
  }
}

function isAccessDeniedOut(text) {
  return /access is denied|отказано в доступе|error:\s*5\b|недостаточно привилегий/i.test(String(text || ''))
}

async function runWgInstall(wgExe, stableConf, runtimeDir, send) {
  send('[WG] Установка службы WireGuardTunnel$wg-turn...')
  const uninstallOut = await runCmdAsync(`"${wgExe}" /uninstalltunnelservice ${TUNNEL_NAME}`, runtimeDir)
  if (uninstallOut && isAccessDeniedOut(uninstallOut)) {
    send('[WG] uninstall: Access is denied — нужны права администратора')
  }
  const installOut = await runCmdAsync(`"${wgExe}" /installtunnelservice "${stableConf}"`, runtimeDir)
  if (installOut) send('[WG] install: ' + installOut.slice(0, 400))
  if (isAccessDeniedOut(installOut)) {
    return { ok: false, accessDenied: true, out: installOut }
  }

  try {
    await execAsync(`sc start "${SERVICE_NAME}"`, {
      windowsHide: true,
      timeout: 20000,
      encoding: 'utf8',
    })
  } catch (e) {
    const msg = [e.stdout, e.stderr, e.message].filter(Boolean).join('\n').trim()
    // 1056 = служба уже запущена (installtunnelservice часто стартует сам)
    if (msg && !/1056|already running|уже запущен/i.test(msg)) {
      send('[WG] sc start: ' + msg.slice(0, 200))
      if (isAccessDeniedOut(msg)) {
        return { ok: false, accessDenied: true, out: msg }
      }
    }
  }
  return { ok: true, accessDenied: false, out: installOut }
}

/**
 * wg.exe syncconf понимает только ключи самого wg (не wg-quick).
 * Address/DNS/MTU → «Line unrecognized» → ложный fallback на uninstall/reinstall.
 */
function stripConfForSyncconf(confText) {
  const drop = new Set(['Address', 'DNS', 'MTU', 'PreUp', 'PostUp', 'PreDown', 'PostDown', 'SaveConfig', 'Table'])
  return normalizeWgConfText(confText)
    .split('\n')
    .filter((line) => {
      const t = line.trim()
      if (!t || t.startsWith('[') || t.startsWith('#')) return true
      const eq = t.indexOf('=')
      if (eq <= 0) return true
      const key = t.slice(0, eq).trim()
      return !drop.has(key)
    })
    .join('\n')
}

async function trySyncConf(runtimeDir, stableConf, send) {
  const wgCli = path.join(runtimeDir, 'wg.exe')
  if (!fs.existsSync(wgCli)) return false
  const syncPath = path.join(STABLE_CONF_DIR, 'wg-turn.sync.conf')
  try {
    const raw = fs.readFileSync(stableConf, 'utf8')
    const forInstall = normalizeWgConfText(raw)
    fs.writeFileSync(stableConf, forInstall, 'utf8')
    const forSync = stripConfForSyncconf(forInstall)
    fs.writeFileSync(syncPath, forSync, 'utf8')
    await execFileAsync(wgCli, ['syncconf', TUNNEL_NAME, syncPath], {
      windowsHide: true,
      timeout: 12000,
    })
    send('[WG] syncconf OK (без переустановки службы)')
    return true
  } catch (e) {
    const msg = [e.stdout, e.stderr, e.message].filter(Boolean).join('\n').trim()
    if (msg) send('[WG] syncconf: ' + msg.slice(0, 200))
    return false
  }
}

function psExec(script) {
  const file = path.join(os.tmpdir(), `silent-wg-${Date.now()}.ps1`)
  try {
    fs.writeFileSync(file, script, 'utf8')
    execSync(`powershell.exe -NoProfile -ExecutionPolicy Bypass -File "${file}"`, {
      windowsHide: true,
      stdio: 'ignore',
      timeout: 30000,
    })
  } catch {} finally {
    try { fs.unlinkSync(file) } catch {}
  }
}

async function psExecAsync(script) {
  const file = path.join(os.tmpdir(), `silent-wg-${Date.now()}-${Math.random().toString(36).slice(2)}.ps1`)
  try {
    fs.writeFileSync(file, script, 'utf8')
    await execAsync(`powershell.exe -NoProfile -ExecutionPolicy Bypass -File "${file}"`, {
      windowsHide: true,
      timeout: 30000,
    })
  } catch { /* ignore */ } finally {
    try { fs.unlinkSync(file) } catch {}
  }
}

function isTunnelUp() {
  try {
    const out = execSync(
      'powershell.exe -NoProfile -Command "Get-NetAdapter -EA SilentlyContinue | ? { ($_.Name -eq \'wg-turn\' -or $_.InterfaceDescription -match \'WireGuard Tunnel\') -and $_.Status -eq \'Up\' } | Select -First 1 -Expand Name"',
      { windowsHide: true, encoding: 'utf8', timeout: 10000 },
    )
    return !!out.trim()
  } catch {
    return false
  }
}

async function isTunnelUpAsync() {
  try {
    const { stdout } = await execAsync(
      'powershell.exe -NoProfile -Command "Get-NetAdapter -EA SilentlyContinue | ? { ($_.Name -eq \'wg-turn\' -or $_.InterfaceDescription -match \'WireGuard Tunnel\') -and $_.Status -eq \'Up\' } | Select -First 1 -Expand Name"',
      { windowsHide: true, encoding: 'utf8', timeout: 10000 },
    )
    return !!String(stdout || '').trim()
  } catch {
    return false
  }
}

/** STATE : 4 = Running (текст локализован на RU Windows). */
function isServiceRunning() {
  try {
    const out = execSync(`sc query "${SERVICE_NAME}"`, { encoding: 'utf8', windowsHide: true })
    if (/\bSTATE\s*:\s*4\b/i.test(out) || /\bСостояние\s*:\s*4\b/i.test(out)) return true
    return /\bRUNNING\b/i.test(out) || /\bРАБОТАЕТ\b/i.test(out)
  } catch {
    return false
  }
}

async function isServiceRunningAsync() {
  try {
    const { stdout } = await execAsync(`sc query "${SERVICE_NAME}"`, {
      encoding: 'utf8',
      windowsHide: true,
      timeout: 8000,
    })
    const out = String(stdout || '')
    if (/\bSTATE\s*:\s*4\b/i.test(out) || /\bСостояние\s*:\s*4\b/i.test(out)) return true
    return /\bRUNNING\b/i.test(out) || /\bРАБОТАЕТ\b/i.test(out)
  } catch {
    return false
  }
}

/** Профиль Private — стабильнее маршруты/DNS на Windows (иконка в трее всё равно от Wi‑Fi). */
async function polishWgNetworkProfile(send) {
  try {
    await execAsync(
      `powershell.exe -NoProfile -Command "& { $a = Get-NetAdapter -EA SilentlyContinue | Where-Object { $_.Name -eq '${TUNNEL_NAME}' -or $_.InterfaceDescription -match 'WireGuard' } | Select-Object -First 1; if ($a) { Set-NetConnectionProfile -InterfaceIndex $a.ifIndex -NetworkCategory Private -ErrorAction SilentlyContinue } }"`,
      { windowsHide: true, timeout: 12000 },
    )
    send?.('[WG] Адаптер wg-turn: профиль Private')
  } catch { /* ignore */ }
}

/** Сохранить default gateway до того, как WG перехватит маршруты. */
async function capturePhysicalGateway(send) {
  try {
    const { stdout } = await execAsync(
      `powershell.exe -NoProfile -Command "$r = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Where-Object { $_.NextHop -ne '0.0.0.0' -and $_.InterfaceAlias -notmatch 'WireGuard|wg-turn' } | Sort-Object RouteMetric | Select-Object -First 1; if ($r) { $r | ConvertTo-Json -Compress }"`,
      { encoding: 'utf8', windowsHide: true, timeout: 12000 },
    )
    const out = String(stdout || '').trim()
    if (!out) return null
    const route = JSON.parse(out)
    if (!route?.NextHop || route.InterfaceIndex == null) return null
    savedPhysicalGateway = {
      nextHop: String(route.NextHop),
      ifIndex: Number(route.InterfaceIndex),
      alias: String(route.InterfaceAlias || ''),
    }
    send?.(`[WG] Шлюз до VPN: ${savedPhysicalGateway.nextHop} (${savedPhysicalGateway.alias || savedPhysicalGateway.ifIndex})`)
    return savedPhysicalGateway
  } catch {
    return null
  }
}

function prefixToMask(prefix) {
  const n = Math.min(32, Math.max(0, Number(prefix) || 32))
  if (n === 0) return '0.0.0.0'
  const mask = n === 32 ? 0xffffffff : ((0xffffffff << (32 - n)) >>> 0)
  return [
    (mask >>> 24) & 255,
    (mask >>> 16) & 255,
    (mask >>> 8) & 255,
    mask & 255,
  ].join('.')
}

function parseBypassTarget(raw) {
  const s = String(raw || '').trim()
  const m = s.match(/^(\d{1,3}(?:\.\d{1,3}){3})(?:\/(\d{1,2}))?$/)
  if (!m) return null
  const ip = m[1]
  const prefix = m[2] != null ? Number(m[2]) : 32
  if (prefix < 0 || prefix > 32) return null
  return { ip, prefix, mask: prefixToMask(prefix), dest: `${ip}/${prefix}` }
}

function buildElevatedBypassBlock(ips) {
  const targets = [...new Set(ips.map(parseBypassTarget).filter(Boolean))]
  if (!targets.length) return ''
  const lines = targets.map(t =>
    `    cmd /c "route delete ${t.ip}" 2>$null | Out-Null\n`
    + `    cmd /c "route add ${t.ip} mask ${t.mask} $($phys.NextHop) metric 0 if $($phys.InterfaceIndex)" 2>$null | Out-Null\n`
    + `    Log "bypass ${t.dest} -> $($phys.NextHop) if $($phys.InterfaceIndex)"`,
  ).join('\n')
  return `
  if ($phys) {
${lines}
  }
`
}

function bypassRoutePs1Lines(ips) {
  const targets = [...new Set(ips.map(parseBypassTarget).filter(Boolean))]
  if (!targets.length) return 'exit 0'
  const arr = targets.map(t => `@{ Ip='${t.ip}'; Mask='${t.mask}'; Dest='${t.dest}' }`).join(', ')
  return `
$BypassTargets = @(${arr})
$phys = $null
if ('${(savedPhysicalGateway?.nextHop || '').replace(/'/g, "''")}' -and ${savedPhysicalGateway?.ifIndex ?? 0}) {
  $phys = [PSCustomObject]@{ NextHop = '${(savedPhysicalGateway?.nextHop || '').replace(/'/g, "''")}'; InterfaceIndex = ${savedPhysicalGateway?.ifIndex ?? 0} }
}
if (-not $phys) {
  $phys = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Where-Object {
    $_.NextHop -ne '0.0.0.0' -and $_.InterfaceAlias -notmatch 'WireGuard|wg-turn'
  } | Sort-Object RouteMetric | Select-Object -First 1
}
if (-not $phys) { exit 2 }
$added = 0
foreach ($t in $BypassTargets) {
  cmd /c "route delete $($t.Ip)" 2>$null | Out-Null
  cmd /c "route add $($t.Ip) mask $($t.Mask) $($phys.NextHop) metric 1 if $($phys.InterfaceIndex)" 2>$null | Out-Null
  Remove-NetRoute -DestinationPrefix $t.Dest -Confirm:$false -ErrorAction SilentlyContinue
  New-NetRoute -DestinationPrefix $t.Dest -NextHop $phys.NextHop -InterfaceIndex $phys.InterfaceIndex -RouteMetric 0 -PolicyStore ActiveStore -ErrorAction SilentlyContinue | Out-Null
  if (Get-NetRoute -DestinationPrefix $t.Dest -ErrorAction SilentlyContinue) { $added++ }
  elseif (cmd /c "route print $($t.Ip)" 2>$null | Select-String -SimpleMatch $t.Ip) { $added++ }
}
if ($added -lt 1) { exit 1 }
`
}

/** Явный маршрут через физический шлюз: IP или CIDR (x.x.x.x/n). */
async function addServerBypassRoutes(excludeIPs, send, options = {}) {
  const targets = [...new Set(
    (excludeIPs || []).map(parseBypassTarget).filter(Boolean).map(t => t.dest),
  )]
  if (!targets.length) return false
  const quiet = options.quiet === true
  const label = String(options.label || 'API').trim() || 'API'
  const chunkSize = 40
  let anyOk = false
  for (let i = 0; i < targets.length; i += chunkSize) {
    const chunk = targets.slice(i, i + chunkSize)
    const scriptPath = path.join(os.tmpdir(), `silent-wg-bypass-${Date.now()}-${i}.ps1`)
    const ps1 = `
$ErrorActionPreference = 'SilentlyContinue'
${bypassRoutePs1Lines(chunk)}
`
    try {
      fs.writeFileSync(scriptPath, ps1, 'utf8')
      await execAsync(`powershell.exe -NoProfile -ExecutionPolicy Bypass -File "${scriptPath}"`, {
        windowsHide: true,
        timeout: Math.min(120000, 20000 + chunk.length * 400),
      })
      anyOk = true
    } catch (e) {
      send?.(`[WG] Bypass ${label} chunk ${Math.floor(i / chunkSize) + 1}: ${e?.message || e}`, 'W')
    } finally {
      try { fs.unlinkSync(scriptPath) } catch {}
    }
  }
  if (!anyOk) {
    send?.(`[WG] Bypass ${label} не применён`, 'W')
    return false
  }
  if (!quiet) {
    const preview = targets.length <= 6 ? targets.join(', ') : `${targets.slice(0, 6).join(', ')}…(+${targets.length - 6})`
    send?.(`[WG] Bypass ${label}: ${preview} → ${savedPhysicalGateway?.nextHop || 'шлюз'}`)
  }
  return true
}

/** Снять host/CIDR routes без сброса сохранённого физического шлюза. */
async function removeHostBypassRoutes(excludeIPs, send) {
  const targets = [...new Set(
    (excludeIPs || []).map(parseBypassTarget).filter(Boolean),
  )]
  if (!targets.length) return
  for (const t of targets) {
    try {
      await execAsync(`route delete ${t.ip}`, { windowsHide: true, timeout: 5000 })
    } catch { /* ignore */ }
    try {
      await execAsync(
        `powershell.exe -NoProfile -Command "Remove-NetRoute -DestinationPrefix '${t.dest}' -Confirm:$false -ErrorAction SilentlyContinue"`,
        { windowsHide: true, timeout: 5000 },
      )
    } catch { /* ignore */ }
  }
  send?.(`[WG] Bypass host routes сняты: ${targets.length}`)
}

async function removeServerBypassRoutes(excludeIPs, send) {
  await removeHostBypassRoutes(excludeIPs, send)
  send?.(`[WG] Bypass API снят: ${(excludeIPs || []).join(', ')}`)
  savedPhysicalGateway = null
}

async function applyWgDns(send) {
  try {
    await execAsync(
      `powershell.exe -NoProfile -Command "& { $a = Get-NetAdapter -EA SilentlyContinue | Where-Object { $_.Name -eq '${TUNNEL_NAME}' -or $_.InterfaceDescription -match 'WireGuard' } | Select-Object -First 1; if ($a) { Set-DnsClientServerAddress -InterfaceIndex $a.ifIndex -ServerAddresses @('1.1.1.1','1.0.0.1','77.88.8.8') -ErrorAction SilentlyContinue } }"`,
      { windowsHide: true, timeout: 12000 },
    )
    send?.('[WG] DNS на адаптере: 1.1.1.1, 1.0.0.1, 77.88.8.8')
  } catch { /* ignore */ }
}

async function finalizeTunnelUp(send, excludeIPs, subnetOnly) {
  await polishWgNetworkProfile(send)
  if (!subnetOnly) {
    await applyWgDns(send)
  }
  if (excludeIPs.length) {
    await addServerBypassRoutes(excludeIPs, send)
  }
}

async function logServiceState(send) {
  try {
    const { stdout } = await execAsync(`sc query "${SERVICE_NAME}"`, {
      encoding: 'utf8',
      windowsHide: true,
      timeout: 8000,
    })
    const out = String(stdout || '')
    const state = (out.match(/STATE\s*:\s*\d+\s+(\S+)/) || out.match(/Состояние\s*:\s*\d+\s+(\S+)/) || [])[1] || '?'
    send(`[WG] Служба ${SERVICE_NAME}: ${state}`)
  } catch {
    send(`[WG] Служба ${SERVICE_NAME} не найдена`)
  }
}

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms))
}

async function waitForTunnelUp(maxMs = 30000, send) {
  const deadline = Date.now() + maxMs
  while (Date.now() < deadline) {
    // sc query быстрее Get-NetAdapter — UI ready раньше
    if (await isServiceRunningAsync()) return true
    await sleep(300)
  }
  const up = await isServiceRunningAsync()
  if (!up) await logServiceState(send)
  return up
}

async function waitForTunnelDown(maxMs = 15000, send) {
  const deadline = Date.now() + maxMs
  while (Date.now() < deadline) {
    if (!(await isTunnelUpAsync()) && !(await isServiceRunningAsync())) return true
    await sleep(400)
  }
  const down = !(await isTunnelUpAsync()) && !(await isServiceRunningAsync())
  if (!down) {
    send?.('[WG] Туннель ещё не остановлен полностью')
    await logServiceState(send)
  }
  return down
}

/** WDTT слушает UDP :9000. Bind-probe быстрее и надёжнее netstat (локаль/права). */
async function isUdpPortListening(port, host = '127.0.0.1') {
  const dgram = require('dgram')
  return new Promise((resolve) => {
    const s = dgram.createSocket('udp4')
    let settled = false
    const done = (v) => {
      if (settled) return
      settled = true
      try { s.close() } catch { /* ignore */ }
      resolve(v)
    }
    s.once('error', (e) => {
      done(/EADDRINUSE/i.test(String(e?.message || e)))
    })
    try {
      s.bind(port, host, () => done(false))
    } catch {
      done(false)
    }
    setTimeout(() => done(false), 400)
  })
}

function waitForPort(host, port, timeoutMs = 8000) {
  return waitForWdttProxy(host, port, timeoutMs)
}

/**
 * Ждём локальный WDTT UDP :9000.
 * confPath: если задан — готовый GETCONF тоже ок (не для api-early!).
 */
async function waitForWdttProxy(host, port, timeoutMs = 60000, send, confPath = null) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (await isUdpPortListening(port, host)) {
      send?.('[WG] WDTT: UDP прокси слушает ' + host + ':' + port)
      return true
    }
    if (confPath && fs.existsSync(confPath)) {
      try {
        const text = fs.readFileSync(confPath, 'utf8')
        if (text.includes('[Interface]') && text.includes(`127.0.0.1:${port}`)) {
          send?.('[WG] WDTT: конфиг wg-turn.conf готов')
          return true
        }
      } catch { /* ignore */ }
    }
    await sleep(50)
  }
  send?.('[WG] WDTT: таймаут ожидания UDP ' + host + ':' + port)
  return false
}

/** Ждём освобождения UDP-порта после kill wdtt (иначе два libclient на 9000). */
async function waitForUdpPortFree(host, port, timeoutMs = 8000, send) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (!(await isUdpPortListening(port, host))) {
      send?.('[WG] UDP ' + host + ':' + port + ' свободен')
      return true
    }
    await sleep(200)
  }
  send?.('[WG] UDP ' + host + ':' + port + ' всё ещё занят')
  return false
}

function copyStableConf(confPath) {
  fs.mkdirSync(STABLE_CONF_DIR, { recursive: true })
  const stable = path.join(STABLE_CONF_DIR, TUNNEL_CONF_NAME)
  const normalized = normalizeWgConfText(fs.readFileSync(confPath, 'utf8'))
  fs.writeFileSync(stable, normalized, 'utf8')
  return stable
}

async function forceStopWireGuard(isDev, dirname, send) {
  return enqueueWgStop(async () => {
    send?.('[WG] Остановка туннеля...')

    const runtimeDir = lastRuntimeDir || prepareRuntimeDir(isDev, dirname, send) || STABLE_WG_DIR
    const wgExe = path.join(runtimeDir, 'wireguard.exe')

    if (fs.existsSync(wgExe)) {
      await runCmdAsync(`"${wgExe}" /uninstalltunnelservice ${TUNNEL_NAME}`, runtimeDir, 20000)
    }

    try {
      await execAsync(`sc stop "${SERVICE_NAME}"`, { windowsHide: true, timeout: 8000 })
    } catch { /* ignore */ }
    try {
      await execAsync(`sc delete "${SERVICE_NAME}"`, { windowsHide: true, timeout: 8000 })
    } catch { /* ignore */ }

    await psExecAsync(`
      Get-CimInstance Win32_Process -Filter "Name='wireguard.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'wg-turn|SilentVPN|SilentVPN' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    `)

    send?.('[WG] Остановка службы wg-turn (переустановка)...')
  })
}

async function stopWireGuardTunnel(isDev, dirname, send, excludeIPs = []) {
  await removeServerBypassRoutes(excludeIPs.length ? excludeIPs : [FALLBACK_BACKEND_IP], send)
  await forceStopWireGuard(isDev, dirname, send)
}

function buildWgConfigFromApi(config, listenPort = 9000) {
  const priv = (config.wg_private_key || '').trim()
  const pub = (config.server_public_key || '').trim()
  if (!priv || !pub) return null
  const addr = (config.wg_address || config.assigned_ip || '').trim()
  if (!addr) return null
  const dns = normalizeDnsValue(config.wg_dns || config.dns, config.dns_override)
  return `[Interface]
PrivateKey = ${priv}
Address = ${addr}
DNS = ${dns}
MTU = 1200

[Peer]
PublicKey = ${pub}
Endpoint = 127.0.0.1:${listenPort}
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
`
}

/** Windows WireGuard tunnel падает (exit 10), если маршрутов слишком много. */
const MAX_WINDOWS_ALLOWED_ROUTES = 32

function countAllowedRoutes(allowedIPsValue) {
  return allowedIPsValue.split(',').map(s => s.trim()).filter(Boolean).length
}

/** wg.exe syncconf на Windows требует «Key = value» (с пробелами). Сервер иногда шлёт Address=… */
function normalizeWgConfText(conf) {
  const known = new Set([
    'PrivateKey', 'Address', 'DNS', 'MTU', 'PublicKey', 'Endpoint',
    'AllowedIPs', 'PersistentKeepalive', 'PresharedKey', 'ListenPort',
  ])
  return String(conf || '')
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .split('\n')
    .map((line) => {
      const trimmed = line.trimEnd()
      const eq = trimmed.indexOf('=')
      if (eq <= 0) return trimmed
      const key = trimmed.slice(0, eq).trim()
      if (!known.has(key)) return trimmed
      const val = trimmed.slice(eq + 1).trim()
      const indent = line.match(/^(\s*)/)?.[1] || ''
      return `${indent}${key} = ${val}`
    })
    .join('\n')
}

function buildAllowedIPsForWindows(excludeIPs, send) {
  // Windows WireGuard:
  // - 0.0.0.0/0 → WFP kill-switch режет WDTT→VK (EACCES), даже с bypass /32
  // - CIDR-exclude 1 IP ≈32 маршрута → 1–2 Мбит, YouTube не грузится
  // - 0.0.0.0/1 + 128.0.0.0/1 = весь IPv4 БЕЗ kill-switch (2 маршрута);
  //   peer/API/VK держим на физ. NIC через addServerBypassRoutes (/32).
  void excludeIPs
  send?.('[WG] AllowedIPs = 0.0.0.0/1, 128.0.0.0/1 (full без kill-switch; API/VK bypass)')
  return '0.0.0.0/1, 128.0.0.0/1'
}

function generateExclusionAllowedIPs(excludeIPs) {
  const ipToNum = ip => ip.split('.').reduce((a, b) => (a << 8 | Number(b)) >>> 0, 0)
  const numToIp = n => [(n >>> 24) & 0xff, (n >>> 16) & 0xff, (n >>> 8) & 0xff, n & 0xff].join('.')

  function cidrExclude(netNum, prefix, excludeNum) {
    const mask = prefix === 0 ? 0 : ((0xffffffff << (32 - prefix)) >>> 0)
    if ((excludeNum & mask) !== (netNum & mask)) return [[netNum, prefix]]
    if (prefix === 32) return []
    const np = prefix + 1
    const left = netNum
    const right = (netNum | (1 << (31 - prefix))) >>> 0
    const nm = ((0xffffffff << (32 - np)) >>> 0)
    if ((excludeNum & nm) === (left & nm)) return [...cidrExclude(left, np, excludeNum), [right, np]]
    return [[left, np], ...cidrExclude(right, np, excludeNum)]
  }

  let networks = [[0, 0]]
  for (const ip of excludeIPs) {
    networks = networks.flatMap(([net, pfx]) => cidrExclude(net, pfx, ipToNum(ip)))
  }
  return networks.map(([n, p]) => `${numToIp(n)}/${p}`).join(', ')
}

function installTunnelElevated(wgExe, stableConf, runtimeDir, send, excludeIPs = [], subnetOnly = false) {
  return new Promise((resolve) => {
    const logPath = path.join(STABLE_CONF_DIR, 'wg-install.log')
    const scriptPath = path.join(STABLE_CONF_DIR, 'wg-install.ps1')
    fs.mkdirSync(STABLE_CONF_DIR, { recursive: true })
    const bypassPs1 = subnetOnly ? '' : buildElevatedBypassBlock(excludeIPs)

    const ps1 = `
$log = '${logPath.replace(/'/g, "''")}'
function Log($m) { Add-Content -Path $log -Value $m -Encoding UTF8 }
Log "=== WG install $(Get-Date -Format o) ==="
try {
  $phys = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Where-Object {
    $_.NextHop -ne '0.0.0.0' -and $_.InterfaceAlias -notmatch 'WireGuard|wg-turn'
  } | Sort-Object RouteMetric | Select-Object -First 1
  if ($phys) { Log "gateway=$($phys.NextHop) if=$($phys.InterfaceAlias)" }
  & '${wgExe.replace(/'/g, "''")}' /uninstalltunnelservice ${TUNNEL_NAME} 2>&1 | ForEach-Object { Log $_ }
  $out = & '${wgExe.replace(/'/g, "''")}' /installtunnelservice '${stableConf.replace(/'/g, "''")}' 2>&1
  $out | ForEach-Object { Log $_ }
  if ($LASTEXITCODE -ne 0) { Log "install exit=$LASTEXITCODE"; exit $LASTEXITCODE }
  sc.exe start '${SERVICE_NAME}' 2>&1 | ForEach-Object { Log $_ }
  Start-Sleep -Milliseconds 400
${bypassPs1}
  Log "OK"
  exit 0
} catch {
  Log "ERROR: $_"
  exit 1
}
`
    fs.writeFileSync(scriptPath, ps1, 'utf8')
    send('[WG] Запрос UAC — нажмите «Да» для установки WireGuard...')

    const launcher = spawn('powershell.exe', [
      '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-Command',
      `Start-Process -FilePath 'powershell.exe' -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','${scriptPath.replace(/'/g, "''")}'`,
    ], { windowsHide: true })

    launcher.on('close', async (code) => {
      if (fs.existsSync(logPath)) {
        const log = fs.readFileSync(logPath, 'utf8').trim()
        log.split('\n').slice(-6).forEach(line => { if (line.trim()) send('[WG] ' + line.trim()) })
      }
      if (code !== 0) {
        send('[WG] UAC отменён или установка не удалась')
        resolve(false)
        return
      }
      const up = await waitForTunnelUp(35000, send)
      if (up) await finalizeTunnelUp(send, excludeIPs, subnetOnly)
      resolve(up)
    })

    launcher.on('error', () => {
      send('[WG] Не удалось запустить UAC')
      resolve(false)
    })
  })
}

async function applyWireGuardConfig(confPath, isDev, dirname, send, excludeIPs = [], options = {}) {
  // Отдать event loop UI (иначе клик тумблера → «Не отвечает» на секунду)
  await sleep(0)
  const skipWdttWait = options.skipWdttWait === true
  const subnetOnly = options.subnetOnly === true
  const skipForceStop = options.skipForceStop === true
  const reuseRuntime = options.reuseRuntime === true
  // Gateway в фоне — не блокировать install (как origin: sync без await-цепочки)
  const gatewayPromise = excludeIPs.length ? capturePhysicalGateway(send) : Promise.resolve(null)
  const runtimeDir = prepareRuntimeDir(isDev, dirname, send, { reuse: reuseRuntime })
  if (!runtimeDir) {
    send('[WG] Нет wireguard.exe / wintun.dll — переустановите Silent VPN')
    return false
  }

  const wgExe = path.join(runtimeDir, 'wireguard.exe')
  send(`[WG] wireguard.exe: ${wgExe}`)

  if (fs.existsSync(confPath)) {
    try {
      let conf = fs.readFileSync(confPath, 'utf8')
      const allowed = subnetOnly
        ? '10.66.66.0/24'
        : buildAllowedIPsForWindows(excludeIPs, send)
      if (subnetOnly) {
        send?.('[WG] AllowedIPs = 10.66.66.0/24 (bootstrap/cred: только API)')
        // DNS через WG при split-route ломает резолв на Windows → «нет интернета»
        conf = conf.replace(/^\s*DNS\s*=.*\r?\n/m, '')
      } else {
        const isFull = allowed === '0.0.0.0/0' || allowed.startsWith('0.0.0.0/1')
        send?.(`[WG] AllowedIPs = ${isFull ? allowed + ' (полный туннель)' : allowed.slice(0, 72) + (allowed.length > 72 ? '…' : '') + ' (split, сервер вне туннеля)'}`)
        const dnsLine = conf.match(/^\s*DNS\s*=\s*(.+)$/m)
        const dns = normalizeDnsValue(dnsLine ? dnsLine[1] : '', options.dnsOverride)
        conf = conf.replace(/^\s*DNS\s*=.*\r?\n/m, '')
        conf = conf.replace(
          /(\[Interface\][^\[]*)/,
          m => `${m.trimEnd()}\nDNS = ${dns}\n`,
        )
        send?.(`[WG] DNS = ${dns}`)
      }
      conf = conf.replace(/AllowedIPs\s*=\s*.+/, `AllowedIPs = ${allowed}`)
      conf = normalizeWgConfText(conf)
      fs.writeFileSync(confPath, conf, 'utf8')
    } catch (e) {
      send('[WG] AllowedIPs: ' + e.message)
    }
  }

  if (!skipWdttWait) {
    send('[WG] Ожидание WDTT...')
    await waitForPort('127.0.0.1', 9000, 8000)
  } else {
    send('[WG] WDTT активен, поднимаем WireGuard...')
  }

  // sc query быстрее Get-NetAdapter
  const serviceUp = await isServiceRunningAsync()
  const stableConf = copyStableConf(confPath)
  send(`[WG] Конфиг: ${stableConf}`)

  // Если служба уже есть — сначала syncconf (1с), не uninstall (5–15с).
  if (serviceUp || skipForceStop) {
    if (await trySyncConf(runtimeDir, stableConf, send)) {
      await gatewayPromise
      await finalizeTunnelUp(send, excludeIPs, subnetOnly)
      send('[WG] Туннель активен (syncconf)')
      return true
    }
    if (skipForceStop) {
      send?.('[WG] syncconf не удался — переустановка службы…', 'W')
    } else {
      send?.('[WG] syncconf не удался — переустановка…', 'W')
    }
    await forceStopWireGuard(isDev, dirname, send)
    await sleep(200)
  } else if (await isTunnelUpAsync()) {
    await forceStopWireGuard(isDev, dirname, () => {})
    await sleep(200)
  }

  const finishOk = async () => {
    await gatewayPromise
    await finalizeTunnelUp(send, excludeIPs, subnetOnly)
    send('[WG] Туннель активен')
    try {
      const wgCli = path.join(runtimeDir, 'wg.exe')
      if (fs.existsSync(wgCli)) {
        const { stdout: st } = await execFileAsync(wgCli, ['show', TUNNEL_NAME], {
          encoding: 'utf8',
          windowsHide: true,
          timeout: 8000,
        })
        String(st || '').split('\n').filter(l => l.trim()).slice(0, 5).forEach(l => send('[WG] ' + l.trim()))
      }
    } catch { /* ignore */ }
    return true
  }

  // Сброс кеша elevation — иначе 60с false-positive после смены прав.
  elevatedCache = { at: 0, value: false }
  const elevated = isProcessElevated()
  send(elevated ? '[WG] Процесс с правами администратора' : '[WG] Без админа — нужен UAC для службы WireGuard')

  if (!elevated) {
    const ok = await installTunnelElevated(wgExe, stableConf, runtimeDir, send, excludeIPs, subnetOnly)
    if (ok) return finishOk()
    send('[WG] Нужны права администратора (UAC). Переустановите Silent VPN или запустите SilentVPN-Admin.bat')
    return false
  }

  const installResult = await runWgInstall(wgExe, stableConf, runtimeDir, send)

  if (await waitForTunnelUp(25000, send)) {
    return finishOk()
  }

  // Сразу после OTA служба/драйвер ещё «остывают» — один повтор без UAC.
  send('[WG] Служба не поднялась — повтор установки через 2с…')
  await sleep(2000)
  const retryResult = await runWgInstall(wgExe, stableConf, runtimeDir, send)
  if (await waitForTunnelUp(25000, send)) {
    return finishOk()
  }

  // Ложный «elevated» или Access Denied — fallback на UAC-скрипт.
  if (installResult.accessDenied || retryResult.accessDenied || !(await isServiceRunningAsync())) {
    send('[WG] Служба не создалась — повтор через UAC…')
    const ok = await installTunnelElevated(wgExe, stableConf, runtimeDir, send, excludeIPs, subnetOnly)
    if (ok) return finishOk()
  }

  await logServiceState(send)
  try {
    const { stdout: evt } = await execAsync(
      `powershell.exe -NoProfile -Command "Get-WinEvent -LogName Application -MaxEvents 30 | Where-Object { $_.ProviderName -match 'WireGuard' } | Select-Object -First 3 -ExpandProperty Message"`,
      { encoding: 'utf8', windowsHide: true, timeout: 8000 },
    )
    if (String(evt || '').trim()) send('[WG] Event log: ' + String(evt).trim().slice(0, 300))
  } catch { /* ignore */ }

  send('[WG] Служба не поднялась — services.msc → WireGuardTunnel$wg-turn')
  send('[WG] Переустановите Silent VPN (установщик чинит WG 1.1) или SilentVPN-Admin.bat')
  return false
}

module.exports = {
  TUNNEL_CONF_NAME,
  TUNNEL_NAME,
  FALLBACK_BACKEND_IP,
  isProcessElevated,
  waitForPort,
  waitForWdttProxy,
  waitForUdpPortFree,
  isUdpPortListening,
  waitForTunnelDown,
  isTunnelUp,
  isServiceRunning,
  isTunnelUpAsync,
  isServiceRunningAsync,
  resetWireGuardState: () => {},
  forceStopWireGuard,
  stopWireGuardTunnel,
  buildWgConfigFromApi,
  applyWireGuardConfig,
  addServerBypassRoutes,
  removeHostBypassRoutes,
  capturePhysicalGateway,
  normalizeWgConfText,
  waitWgStopIdle,
  trySyncConf,
  copyStableConf,
  prepareRuntimeDir,
}
