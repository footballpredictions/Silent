/**
 * Linux: приложения из .desktop (как Start Menu на Windows).
 * Тот же контракт listInstalledApps: { id, name, icon, exePath, source }.
 */
const fs = require('fs')
const os = require('os')
const path = require('path')

const SKIP_NO_DISPLAY = /^(true|1)$/i

function desktopDirs() {
  const home = os.homedir()
  const xdg = process.env.XDG_DATA_DIRS || '/usr/local/share:/usr/share'
  const extra = xdg.split(':').filter(Boolean).map(d => path.join(d, 'applications'))
  return [
    path.join(home, '.local', 'share', 'applications'),
    path.join(home, '.local', 'share', 'flatpak', 'exports', 'share', 'applications'),
    '/var/lib/flatpak/exports/share/applications',
    '/var/lib/snapd/desktop/applications',
    ...extra,
  ]
}

function parseDesktop(text) {
  const map = {}
  let inEntry = false
  for (const raw of String(text || '').split(/\r?\n/)) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    if (line.startsWith('[')) {
      inEntry = line === '[Desktop Entry]'
      continue
    }
    if (!inEntry || !line.includes('=')) continue
    const eq = line.indexOf('=')
    const key = line.slice(0, eq).trim()
    const val = line.slice(eq + 1).trim()
    if (key && map[key] == null) map[key] = val
  }
  return map
}

function stripExecFieldCodes(execLine) {
  return String(execLine || '')
    .replace(/\\"/g, '"')
    .replace(/\s+%[fFuUdDnNickvm]/g, '')
    .trim()
}

function firstArg(execLine) {
  const s = stripExecFieldCodes(execLine)
  if (!s) return ''
  if (s.startsWith('"')) {
    const m = s.match(/^"([^"]+)"/)
    return m ? m[1] : s
  }
  return s.split(/\s+/)[0]
}

function looksLikeApp(entry) {
  const type = String(entry.Type || 'Application')
  if (type !== 'Application') return false
  if (SKIP_NO_DISPLAY.test(entry.NoDisplay || '')) return false
  if (SKIP_NO_DISPLAY.test(entry.Hidden || '')) return false
  if (!entry.Exec || !entry.Name) return false
  return true
}

function findIconPng(iconName) {
  if (!iconName) return ''
  if (iconName.startsWith('/') && fs.existsSync(iconName)) {
    try {
      return 'data:image/png;base64,' + fs.readFileSync(iconName).toString('base64')
    } catch {
      return ''
    }
  }
  const sizes = ['48x48', '32x32', '64x64', '128x128', '24x24']
  const themes = ['hicolor', 'Adwaita', 'gnome']
  for (const theme of themes) {
    for (const size of sizes) {
      for (const ext of ['png', 'svg']) {
        const p = `/usr/share/icons/${theme}/${size}/apps/${iconName}.${ext}`
        if (ext === 'png' && fs.existsSync(p)) {
          try {
            return 'data:image/png;base64,' + fs.readFileSync(p).toString('base64')
          } catch {
            return ''
          }
        }
      }
    }
  }
  return ''
}

function listLinuxDesktopApps() {
  const byId = new Map()
  for (const dir of desktopDirs()) {
    let names = []
    try {
      names = fs.readdirSync(dir).filter(n => n.endsWith('.desktop'))
    } catch {
      continue
    }
    for (const name of names) {
      const filePath = path.join(dir, name)
      let text = ''
      try {
        text = fs.readFileSync(filePath, 'utf8')
      } catch {
        continue
      }
      const entry = parseDesktop(text)
      if (!looksLikeApp(entry)) continue
      const exePath = firstArg(entry.TryExec || entry.Exec)
      if (!exePath) continue
      const id = name.replace(/\.desktop$/i, '')
      if (byId.has(id)) continue
      const icon = findIconPng(entry.Icon || '')
      byId.set(id, {
        id,
        name: entry.Name,
        icon: icon || '',
        exePath,
        source: 'desktop',
      })
    }
  }
  const apps = [...byId.values()]
  apps.sort((a, b) => a.name.localeCompare(b.name, 'ru'))
  return apps
}

module.exports = {
  listLinuxDesktopApps,
  parseDesktop,
  firstArg,
  stripExecFieldCodes,
  looksLikeApp,
}
