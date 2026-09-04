/**
 * Список приложений для исключений VPN.
 * Источники: меню Пуск, Desktop, Steam library, ярлыки BlueStacks.
 */
const { execFileSync } = require('child_process')
const crypto = require('crypto')
const fs = require('fs')
const os = require('os')
const path = require('path')

const SKIP_NAME_RE =
  /(^| )(uninstall|удалить|help|справка|readme|release notes|documentation|website|support|license|лицензия|about|о программе|check for updates|what.?s new|новости|руководство|manual|getting started|online help)( |$)/i

const SKIP_TARGET_RE =
  /\\windows\\|(?:^|\\)(uninstall|unins\d*|setup|install)\.exe$/i

const SKIP_FOLDER_RE =
  /\\(windows (accessories|powershell|system|tools)|administrative tools|system tools|accessibility|maintenance)\\/i

/** Steam redistributables / tools — не игры */
const SKIP_STEAM_APPIDS = new Set([
  '228980', // Steamworks Common Redistributables
  '250820', // SteamVR
  '858280', // Steamworks SDK Redist
])

/**
 * Стабильный id по полному пути. Нельзя truncate base64 пути:
 * chrome.exe и chrome_proxy.exe совпадали в первых 48 символах → Chrome пропадал из списка.
 */
function makeId(targetPath, lnkPath) {
  const base = String(targetPath || lnkPath || '').toLowerCase().replace(/\//g, '\\')
  return crypto.createHash('sha256').update(base).digest('base64url').slice(0, 32)
}

function buildPsScript(outJsonPath) {
  const outLit = String(outJsonPath).replace(/'/g, "''")
  return [
    '$ErrorActionPreference = "Stop"',
    'Add-Type -AssemblyName System.Drawing',
    'function Get-IconPngBase64([string]$path) {',
    '  try {',
    '    if ([string]::IsNullOrWhiteSpace($path)) { return $null }',
    '    if (-not (Test-Path -LiteralPath $path)) { return $null }',
    '    $leaf = [System.IO.Path]::GetFileName($path).ToLowerInvariant()',
    "    if ($leaf -in @('shell32.dll','imageres.dll','moricons.dll','ieframe.dll')) { return $null }",
    '    $icon = [System.Drawing.Icon]::ExtractAssociatedIcon($path)',
    '    if ($null -eq $icon) { return $null }',
    '    $bmp = $icon.ToBitmap()',
    '    $ms = New-Object System.IO.MemoryStream',
    '    $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)',
    '    $b64 = [Convert]::ToBase64String($ms.ToArray())',
    '    $ms.Dispose(); $bmp.Dispose(); $icon.Dispose()',
    '    return $b64',
    '  } catch { return $null }',
    '}',
    'function Resolve-IconBase64([string]$target, [string]$iconLoc, [string]$lnk) {',
    '  $candidates = New-Object System.Collections.Generic.List[string]',
    '  if ($iconLoc) {',
    "    $iconFile = (($iconLoc -split ',')[0]).Trim().Trim('\"')",
    '    if ($iconFile) { [void]$candidates.Add($iconFile) }',
    '  }',
    '  if ($target) { [void]$candidates.Add($target) }',
    '  if ($lnk) { [void]$candidates.Add($lnk) }',
    '  foreach ($p in $candidates) {',
    '    $b64 = Get-IconPngBase64 $p',
    '    if ($b64) { return $b64 }',
    '  }',
    '  return $null',
    '}',
    'function Add-ShortcutRow([string]$fullPath, $shell, $list) {',
    '  try {',
    "    $ext = [System.IO.Path]::GetExtension($fullPath).ToLowerInvariant()",
    '    $name = [System.IO.Path]::GetFileNameWithoutExtension($fullPath)',
    '    if ([string]::IsNullOrWhiteSpace($name)) { return }',
    "    if ($ext -eq '.lnk') {",
    '      $sc = $shell.CreateShortcut($fullPath)',
    '      $target = [string]$sc.TargetPath',
    '      $args = [string]$sc.Arguments',
    '      $iconLoc = [string]$sc.IconLocation',
    '      $wd = [string]$sc.WorkingDirectory',
    '      $url = $null',
    "    } elseif ($ext -eq '.url') {",
    '      $target = $null; $args = $null; $wd = $null; $url = $null; $iconLoc = $null',
    '      foreach ($line in [System.IO.File]::ReadAllLines($fullPath)) {',
    "        if ($line -match '^URL=(.+)$') { $url = $Matches[1].Trim() }",
    "        elseif ($line -match '^IconFile=(.+)$') { $iconLoc = $Matches[1].Trim() }",
    '      }',
    '      if ([string]::IsNullOrWhiteSpace($url)) { return }',
    '      $target = $url',
    '    } else { return }',
    '    if ([string]::IsNullOrWhiteSpace($target) -and [string]::IsNullOrWhiteSpace($url)) { return }',
    '    $iconTarget = $target',
    "    if ($iconTarget -and $iconTarget -match '^(steam|http|https):') { $iconTarget = $null }",
    '    $b64 = Resolve-IconBase64 $iconTarget $iconLoc $fullPath',
    '    $list.Add([pscustomobject]@{',
    '      Name = $name',
    '      LnkPath = $fullPath',
    '      TargetPath = $target',
    '      Arguments = $args',
    '      IconLocation = $iconLoc',
    '      WorkingDirectory = $wd',
    '      IconPngBase64 = $b64',
    '      Kind = $ext.TrimStart(".")',
    '    })',
    '  } catch {}',
    '}',
    '$shell = New-Object -ComObject WScript.Shell',
    '$dirs = New-Object System.Collections.Generic.List[string]',
    "foreach ($p in @(",
    "  (Join-Path ([Environment]::GetFolderPath('StartMenu')) 'Programs'),",
    "  (Join-Path ([Environment]::GetFolderPath('CommonStartMenu')) 'Programs'),",
    "  [Environment]::GetFolderPath('StartMenu'),",
    "  [Environment]::GetFolderPath('CommonStartMenu'),",
    "  [Environment]::GetFolderPath('Desktop'),",
    "  [Environment]::GetFolderPath('CommonDesktopDirectory')",
    ')) {',
    '  if ($p -and (Test-Path -LiteralPath $p)) { [void]$dirs.Add($p) }',
    '}',
    '$list = New-Object System.Collections.Generic.List[object]',
    '$seenLnk = New-Object "System.Collections.Generic.HashSet[string]"',
    'foreach ($dir in $dirs) {',
    // -Include требует суффикс \\* в PS 5.1
    "  $scan = if ($dir.EndsWith('\\')) { $dir + '*' } else { $dir + '\\*' }",
    "  Get-ChildItem -Path $scan -Recurse -Include *.lnk,*.url -ErrorAction SilentlyContinue | ForEach-Object {",
    '    $key = $_.FullName.ToLowerInvariant()',
    '    if (-not $seenLnk.Add($key)) { return }',
    '    Add-ShortcutRow $_.FullName $shell $list',
    '  }',
    '}',
    '$json = ($list | ConvertTo-Json -Compress -Depth 4)',
    'if ([string]::IsNullOrWhiteSpace($json)) { $json = "[]" }',
    '$utf8 = New-Object System.Text.UTF8Encoding $false',
    `[System.IO.File]::WriteAllText('${outLit}', $json, $utf8)`,
  ].join('\r\n')
}

function extractVdfString(block, key) {
  const re = new RegExp(`"${key}"\\s+"([^"]*)"`, 'i')
  const m = String(block || '').match(re)
  return m ? m[1] : ''
}

function getSteamInstallPath() {
  const candidates = [
    process.env['ProgramFiles(x86)'] && path.join(process.env['ProgramFiles(x86)'], 'Steam'),
    process.env.ProgramFiles && path.join(process.env.ProgramFiles, 'Steam'),
  ].filter(Boolean)
  for (const c of candidates) {
    if (fs.existsSync(path.join(c, 'steam.exe'))) return c
  }
  try {
    const out = execFileSync(
      'powershell.exe',
      [
        '-NoProfile', '-NonInteractive', '-Command',
        "(Get-ItemProperty -Path 'HKCU:\\Software\\Valve\\Steam' -EA SilentlyContinue).SteamPath;"
        + "(Get-ItemProperty -Path 'HKLM:\\SOFTWARE\\WOW6432Node\\Valve\\Steam' -EA SilentlyContinue).InstallPath",
      ],
      { encoding: 'utf8', timeout: 8000, windowsHide: true },
    )
    for (const line of String(out || '').split(/\r?\n/)) {
      const p = line.trim().replace(/\//g, '\\')
      if (p && fs.existsSync(path.join(p, 'steam.exe'))) return p
    }
  } catch { /* ignore */ }
  return null
}

function parseSteamLibraryFolders(steamRoot) {
  const vdf = path.join(steamRoot, 'steamapps', 'libraryfolders.vdf')
  const roots = new Set([steamRoot])
  if (!fs.existsSync(vdf)) return [...roots]
  try {
    const text = fs.readFileSync(vdf, 'utf8')
    for (const m of text.matchAll(/"path"\s+"([^"]+)"/gi)) {
      const p = m[1].replace(/\\\\/g, '\\')
      if (p && fs.existsSync(p)) roots.add(p)
    }
  } catch { /* ignore */ }
  return [...roots]
}

function findSteamGameExe(installDir, gameName) {
  if (!installDir || !fs.existsSync(installDir)) return null
  // Не трогаем game\bin\win64 — там основной exe; режем redistrib/tools/crash.
  const skipRe =
    /\\(_commonredist|redistributable|redist|directx|vcredist|crashhandler|tools)\\|uninstall|setup|crashreporter/i
  const preferNames = []
  const base = String(gameName || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '')
  if (base) {
    preferNames.push(`${base}.exe`)
  }
  // common layout shortcuts
  const hints = [
    path.join(installDir, 'game', 'bin', 'win64'),
    path.join(installDir, 'bin', 'win64'),
    path.join(installDir, 'Binaries', 'Win64'),
    installDir,
  ]

  const scored = []
  const walk = (dir, depth) => {
    if (depth > 5 || !fs.existsSync(dir)) return
    let entries
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true })
    } catch {
      return
    }
    for (const ent of entries) {
      const full = path.join(dir, ent.name)
      if (ent.isDirectory()) {
        if (!skipRe.test(full)) walk(full, depth + 1)
        continue
      }
      if (!/\.exe$/i.test(ent.name)) continue
      if (skipRe.test(full)) continue
      let score = 1
      const leaf = ent.name.toLowerCase()
      const leafNorm = leaf.replace(/[^a-z0-9]/g, '')
      if (preferNames.includes(leaf)) score += 100
      if (base && leafNorm.includes(base.slice(0, Math.min(8, base.length)))) score += 40
      if (/\\game\\bin\\win64\\/i.test(full) || /\\binaries\\win64\\/i.test(full)) score += 25
      try {
        score += Math.min(20, Math.log10(fs.statSync(full).size || 1))
      } catch { /* ignore */ }
      scored.push({ full, score })
    }
  }
  for (const h of hints) walk(h, 0)
  scored.sort((a, b) => b.score - a.score)
  return scored[0]?.full || null
}

function listSteamGames() {
  const steamRoot = getSteamInstallPath()
  if (!steamRoot) return []
  const steamExe = path.join(steamRoot, 'steam.exe')
  const apps = []

  for (const libRoot of parseSteamLibraryFolders(steamRoot)) {
    const steamapps = path.join(libRoot, 'steamapps')
    if (!fs.existsSync(steamapps)) continue
    let manifests
    try {
      manifests = fs.readdirSync(steamapps).filter(f => /^appmanifest_\d+\.acf$/i.test(f))
    } catch {
      continue
    }
    for (const file of manifests) {
      const appid = file.match(/appmanifest_(\d+)\.acf/i)?.[1]
      if (!appid || SKIP_STEAM_APPIDS.has(appid)) continue
      let text
      try {
        text = fs.readFileSync(path.join(steamapps, file), 'utf8')
      } catch {
        continue
      }
      const name = extractVdfString(text, 'name')
      const installdir = extractVdfString(text, 'installdir')
      if (!name || !installdir) continue
      if (/^Steamworks/i.test(name) || /Redistributable/i.test(name)) continue

      const commonDir = path.join(steamapps, 'common', installdir)
      let exePath = findSteamGameExe(commonDir, name)
      // fallback: steam.exe still useful for listing / partial exclude
      if (!exePath && fs.existsSync(steamExe)) exePath = steamExe

      const id = makeId(`steam:${appid}`, exePath || commonDir)
      apps.push({
        id,
        name: `${name} (Steam)`,
        installLocation: commonDir,
        exePath: exePath && fs.existsSync(exePath) ? exePath : null,
        lnkPath: '',
        publisher: 'Steam',
        isSystem: false,
        icon: null,
        source: 'steam',
        steamAppId: appid,
      })
    }
  }
  return apps
}

function parseSteamAppIdFromTarget(target) {
  const m = String(target || '').match(/steam:\/\/rungameid\/(\d+)/i)
  return m ? m[1] : null
}

function parseBlueStacksPackage(args) {
  const m = String(args || '').match(/--package\s+"?([a-zA-Z0-9._]+)"?/i)
  return m ? m[1] : null
}

function isBlueStacksPlayer(targetPath) {
  const t = String(targetPath || '').toLowerCase().replace(/\//g, '\\')
  return t.includes('bluestacks') && /hd-player\.exe$/i.test(t)
}

function collectShortcutApps() {
  if (process.platform !== 'win32') return []

  const stamp = `${Date.now()}-${process.pid}`
  const tmpDir = os.tmpdir()
  const psPath = path.join(tmpDir, `silent-apps-${stamp}.ps1`)
  const jsonPath = path.join(tmpDir, `silent-apps-${stamp}.json`)

  let raw = []
  try {
    fs.writeFileSync(psPath, '\uFEFF' + buildPsScript(jsonPath), 'utf8')
    execFileSync(
      'powershell.exe',
      ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', psPath],
      { timeout: 120000, windowsHide: true, maxBuffer: 60 * 1024 * 1024 },
    )

    if (!fs.existsSync(jsonPath)) {
      console.error('[Apps] PowerShell finished but JSON missing:', jsonPath)
      return []
    }

    let text = fs.readFileSync(jsonPath, 'utf8')
    if (text.charCodeAt(0) === 0xfeff) text = text.slice(1)
    text = text.trim()
    if (!text) return []

    const parsed = JSON.parse(text)
    raw = Array.isArray(parsed) ? parsed : [parsed]
  } catch (e) {
    console.error('[Apps] shortcuts scan failed:', e?.stderr?.toString?.() || e?.message || e)
    return []
  } finally {
    try { fs.unlinkSync(psPath) } catch { /* ignore */ }
    try { fs.unlinkSync(jsonPath) } catch { /* ignore */ }
  }

  const steamById = new Map()
  for (const g of listSteamGames()) {
    if (g.steamAppId) steamById.set(g.steamAppId, g)
  }

  const apps = []
  const seen = new Set()

  for (const row of raw) {
    const name = String(row.Name || '').trim()
    const lnkPath = String(row.LnkPath || '').trim()
    let targetPath = String(row.TargetPath || '').trim()
    const args = String(row.Arguments || '').trim()
    if (!name || !lnkPath) continue
    // Яндекс / Yandex никогда не отфильтровываем по «служебным» словам в имени
    const isYandexName = /яндекс|yandex/i.test(name) || /\\yandex\\/i.test(lnkPath)
    if (!isYandexName && SKIP_NAME_RE.test(name)) continue
    if (SKIP_FOLDER_RE.test(lnkPath.replace(/\//g, '\\'))) continue

    const steamAppId = parseSteamAppIdFromTarget(targetPath)
    const bsPackage = parseBlueStacksPackage(args)
    const bsPlayer = isBlueStacksPlayer(targetPath)

    let exePath = null
    let displayName = name
    let publisher = ''
    let installLocation = String(row.WorkingDirectory || '').trim()
    let dedupeKey = (targetPath || lnkPath).toLowerCase()

    if (steamAppId) {
      const steamGame = steamById.get(steamAppId)
      if (steamGame) {
        displayName = steamGame.name
        exePath = steamGame.exePath
        installLocation = steamGame.installLocation
        publisher = 'Steam'
        dedupeKey = `steam:${steamAppId}`
        steamById.delete(steamAppId) // уже из ярлыка
      } else {
        displayName = `${name} (Steam)`
        publisher = 'Steam'
        dedupeKey = `steam:${steamAppId}`
        const steamRoot = getSteamInstallPath()
        const steamExe = steamRoot && path.join(steamRoot, 'steam.exe')
        exePath = steamExe && fs.existsSync(steamExe) ? steamExe : null
      }
    } else if (bsPlayer && bsPackage) {
      displayName = `${name} (BlueStacks)`
      publisher = 'BlueStacks'
      exePath = targetPath
      dedupeKey = `bluestacks:${bsPackage.toLowerCase()}`
    } else if (bsPlayer) {
      displayName = name.includes('BlueStacks') ? name : `${name} (BlueStacks)`
      publisher = 'BlueStacks'
      exePath = targetPath
      dedupeKey = targetPath.toLowerCase()
    } else {
      if (targetPath && SKIP_TARGET_RE.test(targetPath) && !isYandexName) continue
      if (targetPath && /\.exe$/i.test(targetPath) && fs.existsSync(targetPath)) {
        exePath = targetPath
      }
      // Ярлык Яндекса часто на updater/stub — ищем browser.exe рядом
      if (isYandexName && (!exePath || !/browser\.exe$/i.test(exePath))) {
        const near = [
          targetPath && path.join(path.dirname(targetPath), 'browser.exe'),
          targetPath && path.join(path.dirname(targetPath), 'Yandex.exe'),
          process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, 'Yandex', 'YandexBrowser', 'Application', 'browser.exe'),
          process.env.USERPROFILE && path.join(process.env.USERPROFILE, 'AppData', 'Local', 'Yandex', 'YandexBrowser', 'Application', 'browser.exe'),
        ].filter(Boolean)
        for (const cand of near) {
          if (fs.existsSync(cand)) {
            exePath = cand
            displayName = /браузер|browser/i.test(name) ? 'Яндекс Браузер' : name
            break
          }
        }
      }
      if (!installLocation && exePath) installLocation = path.dirname(exePath)
    }

    if (seen.has(dedupeKey)) continue
    seen.add(dedupeKey)

    const b64 = row.IconPngBase64 ? String(row.IconPngBase64).trim() : ''
    const icon = b64 ? `data:image/png;base64,${b64}` : null

    apps.push({
      id: makeId(dedupeKey, lnkPath),
      name: displayName,
      installLocation,
      exePath,
      lnkPath,
      publisher,
      isSystem: false,
      icon,
      source: steamAppId ? 'steam-shortcut' : (bsPackage || bsPlayer ? 'bluestacks' : 'shortcut'),
    })
  }

  // Игры Steam без ярлыка на Desktop (иконку не дёргаем отдельно — дорого)
  for (const g of steamById.values()) {
    const key = `steam:${g.steamAppId}`
    if (seen.has(key)) continue
    seen.add(key)
    apps.push({ ...g, icon: null })
  }

  return apps
}

/** Яндекс / известные пути (часто без ярлыка в Programs; versioned Application\x.y\browser.exe). */
function collectYandexApps() {
  const out = []
  const seen = new Set()

  const add = (exePath, name, source = 'yandex') => {
    const exe = String(exePath || '').trim()
    if (!exe || !/\.exe$/i.test(exe) || !fs.existsSync(exe)) return
    if (/uninstall|setup|update|crash|elevate|notification_helper|chrome_proxy|software_reporter/i.test(exe)) return
    const key = exe.toLowerCase().replace(/\//g, '\\')
    if (seen.has(key)) return
    seen.add(key)
    out.push({
      id: makeId(exe, exe),
      name,
      installLocation: path.dirname(exe),
      exePath: exe,
      lnkPath: '',
      publisher: 'Yandex',
      isSystem: false,
      icon: null,
      source,
    })
  }

  const roots = [
    process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, 'Yandex'),
    process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, 'YandexBrowser'),
    process.env.USERPROFILE && path.join(process.env.USERPROFILE, 'AppData', 'Local', 'Yandex'),
    process.env.USERPROFILE && path.join(process.env.USERPROFILE, 'AppData', 'Local', 'YandexBrowser'),
    process.env.ProgramFiles && path.join(process.env.ProgramFiles, 'Yandex'),
    process.env['ProgramFiles(x86)'] && path.join(process.env['ProgramFiles(x86)'], 'Yandex'),
    process.env.ProgramData && path.join(process.env.ProgramData, 'Yandex'),
  ].filter(Boolean)

  const productHints = [
    { dirRe: /YandexBrowser/i, exeRe: /^(browser|yandex)\.exe$/i, name: 'Яндекс Браузер' },
    { dirRe: /YandexDisk/i, exeRe: /^YandexDisk\d*\.exe$/i, name: 'Яндекс Диск' },
    { dirRe: /YandexMusic/i, exeRe: /^YandexMusic\.exe$/i, name: 'Яндекс Музыка' },
    { dirRe: /YandexMessenger|Yandex\.Messenger/i, exeRe: /\.exe$/i, name: 'Яндекс Мессенджер' },
    { dirRe: /Telemost|YandexTelemost/i, exeRe: /\.exe$/i, name: 'Яндекс Телемост' },
    { dirRe: /Alice/i, exeRe: /^Alice\.exe$/i, name: 'Алиса' },
  ]

  const walkFind = (dir, depth, maxDepth) => {
    if (depth > maxDepth || !fs.existsSync(dir)) return
    let entries
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true })
    } catch {
      return
    }
    for (const ent of entries) {
      const full = path.join(dir, ent.name)
      if (ent.isDirectory()) {
        if (/cache|crash|temp|update|setup|Crashpad|ShaderCache|GPUCache|Code Cache/i.test(ent.name)) continue
        walkFind(full, depth + 1, maxDepth)
        continue
      }
      if (!/\.exe$/i.test(ent.name)) continue
      const lower = full.toLowerCase()
      // Главный бинарь браузера
      if (/\\yandexbrowser\\application\\(?:[\d.]+\\)?browser\.exe$/i.test(lower) ||
          /\\yandexbrowser\\application\\(?:[\d.]+\\)?yandex\.exe$/i.test(lower)) {
        add(full, 'Яндекс Браузер', 'yandex-scan')
        continue
      }
      for (const h of productHints) {
        if (h.dirRe.test(full) && h.exeRe.test(ent.name)) {
          add(full, h.name, 'yandex-scan')
          break
        }
      }
    }
  }

  for (const root of roots) {
    if (!fs.existsSync(root)) continue
    // Прямые кандидаты
    const direct = [
      [path.join(root, 'YandexBrowser', 'Application', 'browser.exe'), 'Яндекс Браузер'],
      [path.join(root, 'Application', 'browser.exe'), 'Яндекс Браузер'],
      [path.join(root, 'YandexBrowser', 'Application', 'Yandex.exe'), 'Яндекс Браузер'],
      [path.join(root, 'YandexDisk', 'YandexDisk2.exe'), 'Яндекс Диск'],
      [path.join(root, 'YandexDisk', 'YandexDisk.exe'), 'Яндекс Диск'],
    ]
    for (const [p, name] of direct) add(p, name, 'yandex')

    // Versioned Application\<ver>\browser.exe
    const appDirs = [
      path.join(root, 'YandexBrowser', 'Application'),
      path.join(root, 'Application'),
    ]
    for (const appDir of appDirs) {
      if (!fs.existsSync(appDir)) continue
      try {
        for (const ent of fs.readdirSync(appDir, { withFileTypes: true })) {
          if (!ent.isDirectory()) continue
          if (!/^\d+\./.test(ent.name)) continue
          add(path.join(appDir, ent.name, 'browser.exe'), 'Яндекс Браузер', 'yandex-ver')
          add(path.join(appDir, ent.name, 'Yandex.exe'), 'Яндекс Браузер', 'yandex-ver')
        }
      } catch { /* ignore */ }
    }
    walkFind(root, 0, 6)
  }

  // Реестр: StartMenuInternet / App Paths / Uninstall (DisplayIcon) — надёжнее ярлыков
  try {
    const stamp = `${Date.now()}-${process.pid}`
    const psPath = path.join(os.tmpdir(), `silent-yandex-${stamp}.ps1`)
    const jsonPath = path.join(os.tmpdir(), `silent-yandex-${stamp}.json`)
    const outLit = jsonPath.replace(/'/g, "''")
    const script = [
      '$ErrorActionPreference = "SilentlyContinue"',
      '$paths = New-Object "System.Collections.Generic.HashSet[string]" ([StringComparer]::OrdinalIgnoreCase)',
      'function Add-Exe([string]$p) {',
      '  if ([string]::IsNullOrWhiteSpace($p)) { return }',
      '  $p = $p.Trim().Trim(\'"\')',
      '  if ($p -match \',\\d+$\' ) { $p = ($p -split \',\')[0].Trim().Trim(\'"\') }',
      '  if ($p -notmatch \'(?i)\\.exe$\') { return }',
      '  if (Test-Path -LiteralPath $p) { [void]$paths.Add((Resolve-Path -LiteralPath $p).Path) }',
      '}',
      // StartMenuInternet clients
      "Get-ChildItem 'HKCU:\\Software\\Clients\\StartMenuInternet','HKLM:\\SOFTWARE\\Clients\\StartMenuInternet' -EA SilentlyContinue | ForEach-Object {",
      "  if ($_.PSChildName -notmatch '(?i)yandex') { return }",
      "  $cmd = (Get-ItemProperty -LiteralPath ($_.PSPath + '\\shell\\open\\command') -EA SilentlyContinue).'(default)'",
      "  if ($cmd -match '\"([^\"]+\\.exe)\"') { Add-Exe $Matches[1] } elseif ($cmd -match '(\\S+\\.exe)') { Add-Exe $Matches[1] }",
      '}',
      // App Paths
      "Get-ChildItem 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\App Paths','HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths' -EA SilentlyContinue | ForEach-Object {",
      "  if ($_.PSChildName -notmatch '(?i)(yandex|browser)') { return }",
      "  $def = (Get-ItemProperty -LiteralPath $_.PSPath -EA SilentlyContinue).'(default)'",
      '  Add-Exe $def',
      '}',
      // Uninstall entries named Yandex / Яндекс
      "$uRoots = @('HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*','HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*','HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*')",
      'Get-ItemProperty $uRoots -EA SilentlyContinue | ForEach-Object {',
      "  $name = [string]$_.DisplayName",
      "  if ($name -notmatch '(?i)yandex|яндекс') { return }",
      '  Add-Exe ([string]$_.DisplayIcon)',
      '  $loc = [string]$_.InstallLocation',
      '  if ($loc -and (Test-Path -LiteralPath $loc)) {',
      "    Get-ChildItem -LiteralPath $loc -Recurse -Filter browser.exe -File -EA SilentlyContinue | Select-Object -First 3 | ForEach-Object { Add-Exe $_.FullName }",
      "    Get-ChildItem -LiteralPath $loc -Recurse -Filter Yandex.exe -File -EA SilentlyContinue | Select-Object -First 3 | ForEach-Object { Add-Exe $_.FullName }",
      '  }',
      '}',
      // Yandex-specific keys
      "foreach ($p in @('HKCU:\\Software\\Yandex\\YandexBrowser','HKLM:\\SOFTWARE\\Yandex\\YandexBrowser')) {",
      '  if (-not (Test-Path -LiteralPath $p)) { continue }',
      '  $props = Get-ItemProperty -LiteralPath $p -EA SilentlyContinue',
      '  foreach ($n in @($props.PSObject.Properties.Name)) {',
      '    $v = [string]$props.$n',
      "    if ($v -match '(?i)\\.exe') { Add-Exe $v }",
      "    if ($v -match '(?i)YandexBrowser' -and (Test-Path -LiteralPath $v)) {",
      "      Get-ChildItem -LiteralPath $v -Recurse -Filter browser.exe -File -EA SilentlyContinue | Select-Object -First 2 | ForEach-Object { Add-Exe $_.FullName }",
      '    }',
      '  }',
      '}',
      '$list = @($paths | ForEach-Object { [pscustomobject]@{ ExePath = $_ } })',
      '$json = ($list | ConvertTo-Json -Compress -Depth 3)',
      'if ([string]::IsNullOrWhiteSpace($json)) { $json = "[]" }',
      `$utf8 = New-Object System.Text.UTF8Encoding $false`,
      `[System.IO.File]::WriteAllText('${outLit}', $json, $utf8)`,
    ].join('\r\n')

    fs.writeFileSync(psPath, '\uFEFF' + script, 'utf8')
    execFileSync(
      'powershell.exe',
      ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', psPath],
      { timeout: 45000, windowsHide: true, maxBuffer: 8 * 1024 * 1024 },
    )
    if (fs.existsSync(jsonPath)) {
      let text = fs.readFileSync(jsonPath, 'utf8')
      if (text.charCodeAt(0) === 0xfeff) text = text.slice(1)
      text = text.trim()
      if (text) {
        const parsed = JSON.parse(text)
        const rows = Array.isArray(parsed) ? parsed : [parsed]
        for (const row of rows) {
          const exe = String(row.ExePath || '').trim()
          if (!exe) continue
          const leaf = path.basename(exe).toLowerCase()
          const name = leaf === 'browser.exe' || leaf === 'yandex.exe'
            ? 'Яндекс Браузер'
            : /disk/i.test(leaf) ? 'Яндекс Диск'
            : /music/i.test(leaf) ? 'Яндекс Музыка'
            : 'Яндекс'
          add(exe, name, 'yandex-reg')
        }
      }
    }
    try { fs.unlinkSync(psPath) } catch { /* ignore */ }
    try { fs.unlinkSync(jsonPath) } catch { /* ignore */ }
  } catch (e) {
    console.error('[Apps] yandex registry scan failed:', e?.message || e)
  }

  return out
}

/** ARP / Uninstall registry — DisplayName + InstallLocation/DisplayIcon. */
function collectUninstallApps() {
  if (process.platform !== 'win32') return []
  const stamp = `${Date.now()}-${process.pid}`
  const tmpDir = os.tmpdir()
  const psPath = path.join(tmpDir, `silent-arp-${stamp}.ps1`)
  const jsonPath = path.join(tmpDir, `silent-arp-${stamp}.json`)
  const outLit = jsonPath.replace(/'/g, "''")
  const script = [
    '$ErrorActionPreference = "SilentlyContinue"',
    '$list = New-Object System.Collections.Generic.List[object]',
    '$roots = @(',
    "  'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',",
    "  'HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',",
    "  'HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*'",
    ')',
    'Get-ItemProperty $roots -EA SilentlyContinue | ForEach-Object {',
    '  $name = [string]$_.DisplayName',
    '  if ([string]::IsNullOrWhiteSpace($name)) { return }',
    '  if ($name -match "(?i)(update|redistributable|runtime|sdk|driver|hotfix|kb\\d)") { return }',
    '  $icon = [string]$_.DisplayIcon',
    '  $loc = [string]$_.InstallLocation',
    '  $exe = $null',
    "  if ($icon) { $exe = (($icon -split ',')[0]).Trim().Trim('\"') }",
    '  if ($exe -and -not ($exe -match "(?i)\\.exe$")) { $exe = $null }',
    '  if (-not $exe -and $loc -and (Test-Path -LiteralPath $loc)) {',
    '    $hit = Get-ChildItem -LiteralPath $loc -Filter *.exe -File -EA SilentlyContinue | Select-Object -First 1',
    '    if ($hit) { $exe = $hit.FullName }',
    '  }',
    '  if (-not $exe -or -not (Test-Path -LiteralPath $exe)) { return }',
    '  $list.Add([pscustomobject]@{ Name = $name; ExePath = $exe; InstallLocation = $loc; Publisher = [string]$_.Publisher })',
    '}',
    `$json = ($list | ConvertTo-Json -Compress -Depth 3)`,
    'if ([string]::IsNullOrWhiteSpace($json)) { $json = "[]" }',
    `$utf8 = New-Object System.Text.UTF8Encoding $false`,
    `[System.IO.File]::WriteAllText('${outLit}', $json, $utf8)`,
  ].join('\r\n')

  try {
    fs.writeFileSync(psPath, '\uFEFF' + script, 'utf8')
    execFileSync(
      'powershell.exe',
      ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', psPath],
      { timeout: 60000, windowsHide: true, maxBuffer: 20 * 1024 * 1024 },
    )
    if (!fs.existsSync(jsonPath)) return []
    let text = fs.readFileSync(jsonPath, 'utf8')
    if (text.charCodeAt(0) === 0xfeff) text = text.slice(1)
    text = text.trim()
    if (!text) return []
    const parsed = JSON.parse(text)
    const rows = Array.isArray(parsed) ? parsed : [parsed]
    return rows.map(row => {
      const name = String(row.Name || '').trim()
      let exePath = String(row.ExePath || '').trim()
      if (!name) return null
      const isYandex = /яндекс|yandex/i.test(name)
      if (!isYandex && SKIP_NAME_RE.test(name)) return null
      // Яндекс: DisplayIcon часто .ico или stub — добираем browser.exe из InstallLocation / LocalAppData
      if (isYandex && (!exePath || !/\.exe$/i.test(exePath) || !fs.existsSync(exePath) || !/browser\.exe$/i.test(exePath))) {
        const loc = String(row.InstallLocation || '').trim()
        const candidates = []
        if (loc) {
          candidates.push(path.join(loc, 'browser.exe'))
          candidates.push(path.join(loc, 'Application', 'browser.exe'))
        }
        candidates.push(
          process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, 'Yandex', 'YandexBrowser', 'Application', 'browser.exe'),
          process.env.USERPROFILE && path.join(process.env.USERPROFILE, 'AppData', 'Local', 'Yandex', 'YandexBrowser', 'Application', 'browser.exe'),
        )
        for (const c of candidates.filter(Boolean)) {
          if (fs.existsSync(c)) {
            exePath = c
            break
          }
        }
      }
      if (!exePath || !/\.exe$/i.test(exePath) || !fs.existsSync(exePath)) return null
      if (!isYandex && SKIP_TARGET_RE.test(exePath)) return null
      return {
        id: makeId(exePath, exePath),
        name: isYandex && /браузер|browser/i.test(name) ? 'Яндекс Браузер' : name,
        installLocation: String(row.InstallLocation || '').trim() || path.dirname(exePath),
        exePath,
        lnkPath: '',
        publisher: String(row.Publisher || '').trim() || (isYandex ? 'Yandex' : ''),
        isSystem: false,
        icon: null,
        source: isYandex ? 'uninstall-yandex' : 'uninstall',
      }
    }).filter(Boolean)
  } catch (e) {
    console.error('[Apps] uninstall scan failed:', e?.message || e)
    return []
  } finally {
    try { fs.unlinkSync(psPath) } catch { /* ignore */ }
    try { fs.unlinkSync(jsonPath) } catch { /* ignore */ }
  }
}

/** Известные браузеры по фиксированным путям (как Yandex) — даже если ярлык потеряли в merge. */
function collectKnownBrowsers() {
  const out = []
  const seen = new Set()
  const add = (exePath, name, publisher) => {
    const exe = String(exePath || '').trim()
    if (!exe || !/\.exe$/i.test(exe) || !fs.existsSync(exe)) return
    if (/chrome_proxy|software_reporter|elevation_service|notification_helper|crashpad|update/i.test(exe)) return
    const key = exe.toLowerCase().replace(/\//g, '\\')
    if (seen.has(key)) return
    seen.add(key)
    out.push({
      id: makeId(exe, exe),
      name,
      installLocation: path.dirname(exe),
      exePath: exe,
      lnkPath: '',
      publisher,
      isSystem: false,
      icon: null,
      source: 'known-browser',
    })
  }

  const pf = process.env.ProgramFiles || 'C:\\Program Files'
  const pf86 = process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)'
  const local = process.env.LOCALAPPDATA || ''

  const candidates = [
    [path.join(pf, 'Google', 'Chrome', 'Application', 'chrome.exe'), 'Google Chrome', 'Google LLC'],
    [path.join(pf86, 'Google', 'Chrome', 'Application', 'chrome.exe'), 'Google Chrome', 'Google LLC'],
    [path.join(local, 'Google', 'Chrome', 'Application', 'chrome.exe'), 'Google Chrome', 'Google LLC'],
    [path.join(pf, 'Google', 'Chrome Beta', 'Application', 'chrome.exe'), 'Google Chrome Beta', 'Google LLC'],
    [path.join(pf, 'Microsoft', 'Edge', 'Application', 'msedge.exe'), 'Microsoft Edge', 'Microsoft Corporation'],
    [path.join(pf86, 'Microsoft', 'Edge', 'Application', 'msedge.exe'), 'Microsoft Edge', 'Microsoft Corporation'],
    [path.join(pf, 'Mozilla Firefox', 'firefox.exe'), 'Mozilla Firefox', 'Mozilla'],
    [path.join(pf86, 'Mozilla Firefox', 'firefox.exe'), 'Mozilla Firefox', 'Mozilla'],
    [path.join(local, 'Mozilla Firefox', 'firefox.exe'), 'Mozilla Firefox', 'Mozilla'],
    [path.join(pf, 'BraveSoftware', 'Brave-Browser', 'Application', 'brave.exe'), 'Brave', 'Brave Software'],
    [path.join(local, 'BraveSoftware', 'Brave-Browser', 'Application', 'brave.exe'), 'Brave', 'Brave Software'],
    [path.join(pf, 'Opera', 'opera.exe'), 'Opera', 'Opera'],
    [path.join(local, 'Programs', 'Opera', 'opera.exe'), 'Opera', 'Opera'],
    [path.join(pf, 'Vivaldi', 'Application', 'vivaldi.exe'), 'Vivaldi', 'Vivaldi'],
    [path.join(local, 'Vivaldi', 'Application', 'vivaldi.exe'), 'Vivaldi', 'Vivaldi'],
  ]
  for (const [exe, name, pub] of candidates) add(exe, name, pub)
  return out
}

function mergeAppLists(...lists) {
  const byExe = new Map()
  const byId = new Map()
  for (const list of lists) {
    for (const app of list || []) {
      let entry = app
      const exeKey = entry.exePath ? String(entry.exePath).toLowerCase().replace(/\//g, '\\') : ''
      if (exeKey && byExe.has(exeKey)) {
        const prev = byExe.get(exeKey)
        if (!prev.icon && entry.icon) prev.icon = entry.icon
        // Предпочитаем «настоящий» браузер chrome.exe, а не chrome_proxy PWA
        if (
          /chrome_proxy\.exe$/i.test(prev.exePath || '') &&
          /chrome\.exe$/i.test(entry.exePath || '') &&
          /chrome/i.test(entry.name || '')
        ) {
          prev.name = entry.name
          prev.exePath = entry.exePath
          prev.publisher = entry.publisher || prev.publisher
          prev.source = entry.source || prev.source
        }
        continue
      }
      if (byId.has(entry.id)) {
        const prev = byId.get(entry.id)
        const prevExe = prev.exePath ? String(prev.exePath).toLowerCase().replace(/\//g, '\\') : ''
        if (exeKey && prevExe && exeKey !== prevExe) {
          // Защита от коллизий id: оставляем оба приложения
          entry = { ...entry, id: makeId(`${exeKey}|${entry.name}|${entry.lnkPath || ''}`, exeKey) }
          if (byId.has(entry.id)) continue
        } else {
          if (!prev.icon && entry.icon) prev.icon = entry.icon
          continue
        }
      }
      byId.set(entry.id, entry)
      if (exeKey) byExe.set(exeKey, entry)
    }
  }
  return [...byId.values()]
}

function listInstalledApps() {
  if (process.platform === 'linux') {
    const { listLinuxDesktopApps } = require('./listInstalledAppsLinux')
    const apps = listLinuxDesktopApps()
    const withIcon = apps.filter(a => a.icon).length
    console.log(`[Apps] linux desktop=${apps.length} icons=${withIcon}`)
    return apps
  }
  if (process.platform !== 'win32') return []

  const shortcuts = collectShortcutApps()
  const yandex = collectYandexApps()
  const browsers = collectKnownBrowsers()
  const uninstall = collectUninstallApps()
  // known browsers раньше uninstall/shortcuts-дублей: имя «Google Chrome», не PWA через chrome_proxy
  const apps = mergeAppLists(browsers, yandex, shortcuts, uninstall)
  apps.sort((a, b) => a.name.localeCompare(b.name, 'ru'))
  const withIcon = apps.filter(a => a.icon).length
  const steamN = apps.filter(a => String(a.source || '').startsWith('steam')).length
  const yaN = apps.filter(a =>
    String(a.source || '').includes('yandex') || /яндекс|yandex/i.test(a.name || ''),
  ).length
  const chromeN = apps.filter(a => /chrome\.exe$/i.test(String(a.exePath || ''))).length
  console.log(
    `[Apps] total=${apps.length} icons=${withIcon} steam=${steamN} yandex=${yaN} chromeExe=${chromeN} uninstall=${uninstall.length}`,
  )
  return apps
}

module.exports = {
  listInstalledApps,
  // для тестов
  parseSteamAppIdFromTarget,
  parseBlueStacksPackage,
  findSteamGameExe,
  extractVdfString,
  collectYandexApps,
  collectKnownBrowsers,
  makeId,
  mergeAppLists,
  normalizePath: (p) => String(p || '').toLowerCase().replace(/\//g, '\\'),
}
