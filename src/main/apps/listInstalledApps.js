/**
 * Список приложений для исключений VPN — ярлыки меню «Пуск».
 * Иконки: System.Drawing ExtractAssociatedIcon (не Electron getFileIcon на .lnk —
 * тот часто отдаёт «белый лист»).
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
    // shell32/imageres — часто «пустой лист» / общий значок
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
    '$shell = New-Object -ComObject WScript.Shell',
    '$dirs = @(',
    "  (Join-Path ([Environment]::GetFolderPath('StartMenu')) 'Programs'),",
    "  (Join-Path ([Environment]::GetFolderPath('CommonStartMenu')) 'Programs')",
    ')',
    '$list = New-Object System.Collections.Generic.List[object]',
    'foreach ($dir in $dirs) {',
    '  if (-not (Test-Path -LiteralPath $dir)) { continue }',
    '  Get-ChildItem -LiteralPath $dir -Recurse -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object {',
    '    try {',
    '      $sc = $shell.CreateShortcut($_.FullName)',
    '      $target = [string]$sc.TargetPath',
    '      $name = [System.IO.Path]::GetFileNameWithoutExtension($_.Name)',
    '      if ([string]::IsNullOrWhiteSpace($name) -or [string]::IsNullOrWhiteSpace($target)) { return }',
    '      $iconLoc = [string]$sc.IconLocation',
    '      $b64 = Resolve-IconBase64 $target $iconLoc $_.FullName',
    '      $list.Add([pscustomobject]@{',
    '        Name = $name',
    '        LnkPath = $_.FullName',
    '        TargetPath = $target',
    '        IconLocation = $iconLoc',
    '        WorkingDirectory = [string]$sc.WorkingDirectory',
    '        IconPngBase64 = $b64',
    '      })',
    '    } catch {}',
    '  }',
    '}',
    '$json = ($list | ConvertTo-Json -Compress -Depth 4)',
    'if ([string]::IsNullOrWhiteSpace($json)) { $json = "[]" }',
    '$utf8 = New-Object System.Text.UTF8Encoding $false',
    `[System.IO.File]::WriteAllText('${outLit}', $json, $utf8)`,
  ].join('\r\n')
}

function listInstalledApps() {
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
      { timeout: 90000, windowsHide: true, maxBuffer: 40 * 1024 * 1024 },
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
    console.error('[Apps] listInstalledApps failed:', e?.stderr?.toString?.() || e?.message || e)
    return []
  } finally {
    try { fs.unlinkSync(psPath) } catch { /* ignore */ }
    try { fs.unlinkSync(jsonPath) } catch { /* ignore */ }
  }

  const seen = new Set()
  const apps = []

  for (const row of raw) {
    const name = String(row.Name || '').trim()
    const lnkPath = String(row.LnkPath || '').trim()
    const targetPath = String(row.TargetPath || '').trim()
    if (!name || !lnkPath) continue
    if (SKIP_NAME_RE.test(name)) continue
    if (SKIP_FOLDER_RE.test(lnkPath.replace(/\//g, '\\'))) continue
    if (targetPath && SKIP_TARGET_RE.test(targetPath)) continue

    const dedupeKey = (targetPath || lnkPath).toLowerCase()
    if (seen.has(dedupeKey)) continue
    seen.add(dedupeKey)

    const exePath =
      targetPath && /\.exe$/i.test(targetPath) && fs.existsSync(targetPath)
        ? targetPath
        : null

    const b64 = row.IconPngBase64 ? String(row.IconPngBase64).trim() : ''
    const icon = b64 ? `data:image/png;base64,${b64}` : null

    apps.push({
      id: makeId(targetPath || lnkPath, lnkPath),
      name,
      installLocation: String(row.WorkingDirectory || path.dirname(targetPath || '') || '').trim(),
      exePath,
      lnkPath,
      publisher: '',
      isSystem: false,
      icon,
    })
  }

  apps.sort((a, b) => a.name.localeCompare(b.name, 'ru'))
  const withIcon = apps.filter(a => a.icon).length
  console.log(`[Apps] start-menu shortcuts: ${apps.length}, icons: ${withIcon}`)
  return apps
}

module.exports = { listInstalledApps }
