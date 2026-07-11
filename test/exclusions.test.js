/**
 * Unit / auto tests: исключения приложений PC.
 * Запуск: npm test
 */
const { describe, it } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('fs')
const os = require('os')
const path = require('path')

const {
  resolveExcludedExePaths,
  isProcessExcluded,
  normalizePath,
} = require('../src/main/apps/exclusionsPolicy')
const {
  saveExclusionsState,
  loadExclusionsState,
  getExcludedExePathsForVpn,
} = require('../src/main/apps/exclusionsState')
const {
  applyAppExclusionsForSession,
  assertExeExcludedInSession,
  clearActiveExcludedExePaths,
  getActiveExcludedExePaths,
} = require('../src/main/apps/vpnAppExclusions')

describe('exclusionsPolicy', () => {
  const apps = [
    { id: 'chrome', name: 'Google Chrome', exePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe' },
    { id: 'telegram', name: 'Telegram', exePath: 'C:\\Users\\me\\AppData\\Roaming\\Telegram Desktop\\Telegram.exe' },
    { id: 'noexe', name: 'Store App', exePath: null },
    { id: 'dup', name: 'Chrome copy', exePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe' },
  ]

  it('resolveExcludedExePaths maps selected ids to unique .exe paths', () => {
    const { exePaths, entries } = resolveExcludedExePaths(new Set(['chrome', 'telegram', 'noexe']), apps)
    assert.equal(exePaths.length, 2)
    assert.ok(exePaths.some(p => /chrome\.exe$/i.test(p)))
    assert.ok(exePaths.some(p => /Telegram\.exe$/i.test(p)))
    assert.equal(entries.length, 2)
  })

  it('dedupes same exe from different ids', () => {
    const { exePaths } = resolveExcludedExePaths(['chrome', 'dup'], apps)
    assert.equal(exePaths.length, 1)
  })

  it('ignores unknown ids', () => {
    const { exePaths } = resolveExcludedExePaths(['missing'], apps)
    assert.deepEqual(exePaths, [])
  })

  it('isProcessExcluded matches full path and basename', () => {
    const list = ['C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe']
    assert.equal(isProcessExcluded('C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', list), true)
    assert.equal(isProcessExcluded('c:/program files/google/chrome/application/chrome.exe', list), true)
    assert.equal(isProcessExcluded('D:\\Other\\chrome.exe', list), true)
    assert.equal(isProcessExcluded('C:\\Program Files\\Mozilla Firefox\\firefox.exe', list), false)
  })

  it('normalizePath lowercases and unifies separators', () => {
    assert.equal(normalizePath('C:/Foo/Bar.EXE'), 'c:\\foo\\bar.exe')
  })
})

describe('exclusionsState persistence', () => {
  it('save/load roundtrip and getExcludedExePathsForVpn', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'silent-excl-'))
    const filePath = path.join(dir, 'app-exclusions.json')
    const apps = [
      { id: 'a', name: 'App A', exePath: 'C:\\Apps\\A\\a.exe' },
      { id: 'b', name: 'App B', exePath: 'C:\\Apps\\B\\b.exe' },
    ]
    const saved = saveExclusionsState({
      filePath,
      selectedIds: ['a'],
      apps,
    })
    assert.deepEqual(saved.exePaths, ['C:\\Apps\\A\\a.exe'])

    const loaded = loadExclusionsState(filePath)
    assert.deepEqual(loaded.selectedIds, ['a'])
    assert.deepEqual(loaded.exePaths, ['C:\\Apps\\A\\a.exe'])
    assert.deepEqual(getExcludedExePathsForVpn(filePath), ['C:\\Apps\\A\\a.exe'])

    fs.rmSync(dir, { recursive: true, force: true })
  })
})

describe('vpn session exclusions — приложение реально в плане сессии', () => {
  it('applyAppExclusionsForSession then assertExeExcludedInSession', () => {
    clearActiveExcludedExePaths()
    const chrome = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
    const tg = 'C:\\Users\\me\\AppData\\Roaming\\Telegram Desktop\\Telegram.exe'
    const logs = []
    const result = applyAppExclusionsForSession([chrome, tg], (l) => logs.push(l))
    assert.equal(result.applied.length, 2)
    assert.equal(assertExeExcludedInSession(chrome), true)
    assert.equal(assertExeExcludedInSession(tg), true)
    assert.equal(assertExeExcludedInSession('C:\\Windows\\notepad.exe'), false)
    assert.equal(getActiveExcludedExePaths().length, 2)
    assert.ok(logs.some(l => /исключения сессии/.test(l)))
    clearActiveExcludedExePaths()
  })

  it('full pipeline: UI selection → state file → VPN session plan', () => {
    clearActiveExcludedExePaths()
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'silent-excl-pipe-'))
    const filePath = path.join(dir, 'app-exclusions.json')
    const apps = [
      { id: 'chrome', name: 'Google Chrome', exePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe' },
      { id: 'edge', name: 'Edge', exePath: 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe' },
    ]

    // Пользователь отметил только Chrome
    saveExclusionsState({ filePath, selectedIds: ['chrome'], apps })
    const forVpn = getExcludedExePathsForVpn(filePath)
    assert.deepEqual(forVpn, [apps[0].exePath])

    applyAppExclusionsForSession(forVpn)
    assert.equal(assertExeExcludedInSession(apps[0].exePath), true)
    assert.equal(assertExeExcludedInSession(apps[1].exePath), false)

    clearActiveExcludedExePaths()
    fs.rmSync(dir, { recursive: true, force: true })
  })
})

describe('listInstalledApps (Windows integration)', () => {
  it('returns Start Menu apps with icons and some exePath', { skip: process.platform !== 'win32' }, () => {
    const { listInstalledApps } = require('../src/main/apps/listInstalledApps')
    const apps = listInstalledApps()
    assert.ok(apps.length > 0, 'ожидались ярлыки меню Пуск')
    const withIcon = apps.filter(a => a.icon && String(a.icon).startsWith('data:image/png'))
    assert.ok(withIcon.length > 0, 'ожидались PNG-иконки')
    const withExe = apps.filter(a => a.exePath && /\.exe$/i.test(a.exePath))
    assert.ok(withExe.length > 0, 'ожидались пути .exe')

    // Резолв: если выбрать первое приложение с exe — оно попадает в план исключений
    const pick = withExe[0]
    const { exePaths } = resolveExcludedExePaths(new Set([pick.id]), apps)
    assert.ok(exePaths.includes(pick.exePath))
    applyAppExclusionsForSession(exePaths)
    assert.equal(assertExeExcludedInSession(pick.exePath), true)
    clearActiveExcludedExePaths()
  })
})

describe('VPN wiring in main.js', () => {
  it('main.js loads exclusion modules on connect path', () => {
    const mainSrc = fs.readFileSync(path.join(__dirname, '../src/main/main.js'), 'utf8')
    assert.match(mainSrc, /getExcludedExePathsForVpn/)
    assert.match(mainSrc, /applyAppExclusionsForSession/)
    assert.match(mainSrc, /save-app-exclusions/)
    assert.match(mainSrc, /clearActiveExcludedExePaths/)
  })
})
