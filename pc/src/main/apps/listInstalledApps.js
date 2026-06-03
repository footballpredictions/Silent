/**
 * Список установленных программ Windows (для исключений VPN).
 */
const { execSync } = require('child_process')
const fs = require('fs')
const path = require('path')
const { nativeImage } = require('electron')

function isSystemApp(entry) {
  const pub = String(entry.publisher || '').toLowerCase()
  const loc = String(entry.installLocation || '').toLowerCase()
  const name = String(entry.name || '').toLowerCase()

  if (loc.includes('\\windows\\')) return true
  if (loc.includes('\\program files\\windowsapps\\')) return true
  if (loc.includes('\\program files (x86)\\windows kits\\')) return true

  if (pub.includes('microsoft')) {
    if (loc.includes('\\users\\') && loc.includes('\\appdata\\local\\programs\\')) return false
    if (loc.includes('\\program files\\') && !loc.includes('\\windowsapps\\')) return false
    if (name.startsWith('microsoft ') || name.startsWith('windows ')) return true
    if (!loc && pub.includes('microsoft corporation')) return true
  }
  return false
}

function normalizeIconPath(raw) {
  if (!raw) return null
  let p = String(raw).split(',')[0].trim().replace(/^"(.*)"$/, '$1')
  if (!p) return null
  if (p.includes('%')) {
    p = p.replace(/%ProgramFiles\(x86\)%/gi, process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)')
    p = p.replace(/%ProgramFiles%/gi, process.env.ProgramFiles || 'C:\\Program Files')
    p = p.replace(/%LocalAppData%/gi, process.env.LOCALAPPDATA || '')
    p = p.replace(/%AppData%/gi, process.env.APPDATA || '')
  }
  if (!fs.existsSync(p)) return null
  return p
}

function iconToDataUrl(iconPath) {
  try {
    const img = nativeImage.createFromPath(iconPath)
    if (img.isEmpty()) return null
    return img.resize({ width: 32, height: 32 }).toDataURL()
  } catch {
    return null
  }
}

function makeId(name, installLocation, iconPath) {
  const base = `${name}|${installLocation || ''}|${iconPath || ''}`.toLowerCase()
  return Buffer.from(base).toString('base64url').slice(0, 48)
}

function listInstalledApps() {
  if (process.platform !== 'win32') return []

  const ps = `
$keys = @(
  'HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',
  'HKLM:\\Software\\Wow6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',
  'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*'
)
Get-ItemProperty $keys -ErrorAction SilentlyContinue |
  Where-Object { $_.DisplayName -and $_.SystemComponent -ne 1 } |
  Select-Object DisplayName, DisplayIcon, InstallLocation, Publisher |
  ConvertTo-Json -Compress
`

  let raw = []
  try {
    const out = execSync(
      `powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "${ps.replace(/"/g, '\\"').replace(/\n/g, ' ')}"`,
      { encoding: 'utf8', timeout: 60000, windowsHide: true, maxBuffer: 20 * 1024 * 1024 },
    ).trim()
    if (!out) return []
    const parsed = JSON.parse(out)
    raw = Array.isArray(parsed) ? parsed : [parsed]
  } catch {
    return []
  }

  const seen = new Set()
  const apps = []

  for (const row of raw) {
    const name = String(row.DisplayName || '').trim()
    if (!name || name.length < 2) continue
    const key = name.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)

    const installLocation = String(row.InstallLocation || '').trim()
    const iconPath = normalizeIconPath(row.DisplayIcon)
    const publisher = String(row.Publisher || '').trim()
    const id = makeId(name, installLocation, iconPath)

    apps.push({
      id,
      name,
      installLocation,
      exePath: iconPath && iconPath.toLowerCase().endsWith('.exe') ? iconPath : null,
      publisher,
      isSystem: isSystemApp({ name, installLocation, publisher }),
      icon: iconToDataUrl(iconPath),
    })
  }

  apps.sort((a, b) => a.name.localeCompare(b.name, 'ru'))
  return apps
}

module.exports = { listInstalledApps }
