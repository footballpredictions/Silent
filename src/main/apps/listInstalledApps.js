/**
 * Список приложений для исключений VPN.
 * Источники: меню Пуск, Desktop, Steam library, ярлыки BlueStacks.
 */
const { execFileSync } = require('child_process')
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

function makeId(targetPath, lnkPath) {
  const base = String(targetPath || lnkPath || '').toLowerCase()
  return Buffer.from(base).toString('base64url').slice(0, 48)
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
    "  Get-ChildItem -LiteralPath $dir -Recurse -Include *.lnk,*.url -ErrorAction SilentlyContinue | ForEach-Object {",
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
    if (SKIP_NAME_RE.test(name)) continue
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
      if (targetPath && SKIP_TARGET_RE.test(targetPath)) continue
      if (targetPath && /\.exe$/i.test(targetPath) && fs.existsSync(targetPath)) {
        exePath = targetPath
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

function listInstalledApps() {
  if (process.platform !== 'win32') return []

  const apps = collectShortcutApps()
  apps.sort((a, b) => a.name.localeCompare(b.name, 'ru'))
  const withIcon = apps.filter(a => a.icon).length
  const steamN = apps.filter(a => String(a.source || '').startsWith('steam')).length
  const bsN = apps.filter(a => a.source === 'bluestacks').length
  console.log(
    `[Apps] total=${apps.length} icons=${withIcon} steam=${steamN} bluestacks=${bsN}`,
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
}
