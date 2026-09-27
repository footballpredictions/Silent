/**
 * macOS: приложения из /Applications (как меню Пуск на Windows).
 * exePath — путь к .app. Обход туннеля смотрит процессы внутри этого бандла.
 */
const crypto = require('crypto')
const fs = require('fs')
const os = require('os')
const path = require('path')

function makeId(appPath) {
  const base = String(appPath || '').toLowerCase().replace(/\//g, '\\')
  return crypto.createHash('sha256').update(base).digest('base64url').slice(0, 32)
}

function readDisplayName(appPath, fallback) {
  const plist = path.join(appPath, 'Contents', 'Info.plist')
  try {
    const buf = fs.readFileSync(plist)
    if (buf.slice(0, 6).toString('latin1') === 'bplist') return fallback
    const text = buf.toString('utf8')
    const display = text.match(/<key>CFBundleDisplayName<\/key>\s*<string>([^<]*)<\/string>/)
    const name = text.match(/<key>CFBundleName<\/key>\s*<string>([^<]*)<\/string>/)
    const raw = (display && display[1]) || (name && name[1]) || ''
    const cleaned = raw.replace(/&amp;/g, '&').replace(/&lt;/g, '<').trim()
    return cleaned || fallback
  } catch {
    return fallback
  }
}

function addApp(dir, name, apps, seen) {
  const appPath = path.join(dir, name)
  const key = appPath.toLowerCase()
  if (seen.has(key)) return
  seen.add(key)
  const fallback = name.replace(/\.app$/i, '')
  apps.push({
    id: makeId(appPath),
    name: readDisplayName(appPath, fallback),
    icon: '',
    exePath: appPath,
    source: 'mac-app',
  })
}

function scanRoot(root, apps, seen, depth) {
  let entries = []
  try {
    entries = fs.readdirSync(root, { withFileTypes: true })
  } catch {
    return
  }
  for (const ent of entries) {
    if (ent.name.startsWith('.')) continue
    if (ent.name.toLowerCase().endsWith('.app')) {
      addApp(root, ent.name, apps, seen)
      continue
    }
    if (depth > 0 && ent.isDirectory()) {
      scanRoot(path.join(root, ent.name), apps, seen, depth - 1)
    }
  }
}

function defaultRoots() {
  return [
    '/Applications',
    path.join(os.homedir(), 'Applications'),
    '/System/Applications',
  ]
}

function listMacApps(roots) {
  const apps = []
  const seen = new Set()
  for (const root of roots && roots.length ? roots : defaultRoots()) {
    scanRoot(root, apps, seen, 1)
  }
  apps.sort((a, b) => a.name.localeCompare(b.name, 'ru'))
  return apps
}

module.exports = {
  listMacApps,
  readDisplayName,
}
