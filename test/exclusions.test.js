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
  resolveBypassExePaths,
  isProcessExcluded,
  normalizePath,
} = require('../src/main/apps/exclusionsPolicy')
const {
  parseRules,
  normalizeRuleInput,
  extractRulesFromImportContent,
  mergeImportRules,
  MAX_RULES,
} = require('../src/main/apps/siteBypass')
const {
  saveExclusionsState,
  loadExclusionsState,
  getExcludedExePathsForVpn,
} = require('../src/main/apps/exclusionsState')
const {
  hydrateExclusions,
  switchExclusionsMode,
  setActiveIds,
  applySave,
} = require('../src/main/apps/exclusionsPersist')
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

  it('whitelist mode bypasses all except selected', () => {
    const { exePaths } = resolveBypassExePaths({
      selectedIds: ['chrome'],
      apps,
      whitelist: true,
    })
    assert.ok(exePaths.some(p => /Telegram\.exe$/i.test(p)))
    assert.ok(!exePaths.some(p => /chrome\.exe$/i.test(p)))
  })

  it('blacklist mode matches resolveExcludedExePaths', () => {
    const a = resolveBypassExePaths({ selectedIds: ['telegram'], apps, whitelist: false })
    const b = resolveExcludedExePaths(['telegram'], apps)
    assert.deepEqual(a.exePaths, b.exePaths)
  })

  it('empty whitelist is fail-safe: nothing bypassed (all traffic in VPN)', () => {
    const { exePaths } = resolveBypassExePaths({ selectedIds: [], apps, whitelist: true })
    assert.deepEqual(exePaths, [])
  })
})

describe('siteBypass rules', () => {
  it('normalizeRuleInput strips url', () => {
    assert.equal(normalizeRuleInput('https://ozon.ru/product/1'), 'ozon.ru')
    assert.equal(normalizeRuleInput('10.0.0.0/8'), '10.0.0.0/8')
  })

  it('parseRules dedupes and caps', () => {
    const rules = parseRules('ozon.ru\n#x\nozon.ru\n1.2.3.4')
    assert.deepEqual(rules, ['ozon.ru', '1.2.3.4'])
  })

  it('extractRulesFromImportContent reads json rules array', () => {
    const content = '{"version":1,"rules":["ozon.ru","https://whoer.net/ru","1.2.3.4"]}'
    const rules = extractRulesFromImportContent(content)
    assert.ok(rules.includes('ozon.ru'))
    assert.ok(rules.includes('whoer.net'))
    assert.ok(rules.includes('1.2.3.4'))
    assert.equal(rules.length, 3)
  })

  it('extractRulesFromImportContent reads plain txt and csv', () => {
    const content = '# comment\nozon.ru\ntelegram.org, 8.8.8.8\n'
    const rules = extractRulesFromImportContent(content)
    assert.ok(rules.includes('ozon.ru'))
    assert.ok(rules.includes('telegram.org'))
    assert.ok(rules.includes('8.8.8.8'))
  })

  it('mergeImportRules keeps unique and respects limit', () => {
    const merged = mergeImportRules(
      ['ozon.ru'],
      ['ozon.ru', 'whoer.net', '1.2.3.4'],
      MAX_RULES,
    )
    assert.deepEqual(merged, ['ozon.ru', 'whoer.net', '1.2.3.4'])
  })
})

describe('exclusionsPersist helper', () => {
  it('switch mode keeps the other list in memory', () => {
    let state = hydrateExclusions({ selectedIds: [], whitelist: false })
    state = setActiveIds({ ...state, whitelist: true, appBypassMode: 'whitelist' }, ['A', 'B'])
    state = switchExclusionsMode(state, false)
    state = setActiveIds(state, ['C', 'D', 'E'])
    state = switchExclusionsMode(state, true)
    assert.deepEqual(state.whitelistAppIds.sort(), ['A', 'B'])
    assert.deepEqual(state.blacklistAppIds.sort(), ['C', 'D', 'E'])
    assert.equal(state.whitelist, true)
  })

  it('applySave after restart hydrate keeps blacklist mode', () => {
    const saved = applySave(null, { selectedIds: ['C', 'D', 'E'], whitelist: false })
    const reloaded = hydrateExclusions(saved)
    assert.equal(reloaded.whitelist, false)
    assert.equal(reloaded.appBypassMode, 'blacklist')
    assert.deepEqual(reloaded.blacklistAppIds.sort(), ['C', 'D', 'E'])
  })
})

describe('dual list persistence — mode switch must not wipe the other list', () => {
  const apps = [
    { id: 'A', name: 'App A', exePath: 'C:\\Apps\\A\\a.exe' },
    { id: 'B', name: 'App B', exePath: 'C:\\Apps\\B\\b.exe' },
    { id: 'C', name: 'App C', exePath: 'C:\\Apps\\C\\c.exe' },
    { id: 'D', name: 'App D', exePath: 'C:\\Apps\\D\\d.exe' },
    { id: 'E', name: 'App E', exePath: 'C:\\Apps\\E\\e.exe' },
  ]

  it('whitelist [A,B] then blacklist [C,D,E] then back — both lists survive', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'silent-excl-dual-'))
    const filePath = path.join(dir, 'app-exclusions.json')
    try {
      saveExclusionsState({ filePath, selectedIds: ['A', 'B'], apps, whitelist: true })
      saveExclusionsState({ filePath, selectedIds: ['C', 'D', 'E'], apps, whitelist: false })
      const afterBlack = loadExclusionsState(filePath)
      assert.equal(afterBlack.whitelist, false)
      assert.deepEqual([...afterBlack.whitelistAppIds].sort(), ['A', 'B'])
      assert.deepEqual([...afterBlack.blacklistAppIds].sort(), ['C', 'D', 'E'])
      assert.deepEqual([...afterBlack.selectedIds].sort(), ['C', 'D', 'E'])

      saveExclusionsState({
        filePath,
        selectedIds: afterBlack.whitelistAppIds,
        apps,
        whitelist: true,
        blacklistAppIds: afterBlack.blacklistAppIds,
        whitelistAppIds: afterBlack.whitelistAppIds,
      })
      const afterWhite = loadExclusionsState(filePath)
      assert.equal(afterWhite.whitelist, true)
      assert.deepEqual([...afterWhite.whitelistAppIds].sort(), ['A', 'B'])
      assert.deepEqual([...afterWhite.blacklistAppIds].sort(), ['C', 'D', 'E'])
      assert.deepEqual([...afterWhite.selectedIds].sort(), ['A', 'B'])
    } finally {
      fs.rmSync(dir, { recursive: true, force: true })
    }
  })

  it('persist + reload keeps blacklist mode (restart hydrate)', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'silent-excl-hydrate-'))
    const filePath = path.join(dir, 'app-exclusions.json')
    try {
      saveExclusionsState({ filePath, selectedIds: ['C', 'D', 'E'], apps, whitelist: false })
      const reloaded = loadExclusionsState(filePath)
      assert.equal(reloaded.whitelist, false)
      assert.deepEqual([...reloaded.blacklistAppIds].sort(), ['C', 'D', 'E'])
      assert.equal(reloaded.appBypassMode, 'blacklist')
    } finally {
      fs.rmSync(dir, { recursive: true, force: true })
    }
  })

  it('migrates legacy single selectedIds into the then-active list', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'silent-excl-mig-'))
    const filePath = path.join(dir, 'app-exclusions.json')
    try {
      fs.writeFileSync(filePath, JSON.stringify({
        version: 2,
        whitelist: false,
        selectedIds: ['A'],
        apps,
      }), 'utf8')
      const loaded = loadExclusionsState(filePath)
      assert.deepEqual(loaded.blacklistAppIds, ['A'])
      assert.deepEqual(loaded.whitelistAppIds, [])
      assert.equal(loaded.whitelist, false)

      fs.writeFileSync(filePath, JSON.stringify({
        version: 2,
        whitelist: true,
        selectedIds: ['B'],
        apps,
      }), 'utf8')
      const wl = loadExclusionsState(filePath)
      assert.deepEqual(wl.whitelistAppIds, ['B'])
      assert.deepEqual(wl.blacklistAppIds, [])
      assert.equal(wl.whitelist, true)
    } finally {
      fs.rmSync(dir, { recursive: true, force: true })
    }
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
    void clearActiveExcludedExePaths()
    const chrome = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
    const tg = 'C:\\Users\\me\\AppData\\Roaming\\Telegram Desktop\\Telegram.exe'
    const logs = []
    const result = applyAppExclusionsForSession([chrome, tg], (l) => logs.push(l), { enableBypass: false })
    assert.equal(result.applied.length, 2)
    assert.equal(assertExeExcludedInSession(chrome), true)
    assert.equal(assertExeExcludedInSession(tg), true)
    assert.equal(assertExeExcludedInSession('C:\\Windows\\notepad.exe'), false)
    assert.equal(getActiveExcludedExePaths().length, 2)
    assert.ok(logs.some(l => /исключения сессии/.test(l)))
    void clearActiveExcludedExePaths()
  })

  it('full pipeline: UI selection → state file → VPN session plan', () => {
    void clearActiveExcludedExePaths()
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'silent-excl-pipe-'))
    const filePath = path.join(dir, 'app-exclusions.json')
    const apps = [
      { id: 'chrome', name: 'Google Chrome', exePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe' },
      { id: 'edge', name: 'Edge', exePath: 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe' },
    ]

    // Пользователь отметил только Chrome (ЧС)
    saveExclusionsState({ filePath, selectedIds: ['chrome'], apps, whitelist: false })
    const forVpn = getExcludedExePathsForVpn(filePath)
    assert.deepEqual(forVpn, [apps[0].exePath])

    applyAppExclusionsForSession(forVpn, () => {}, { enableBypass: false })
    assert.equal(assertExeExcludedInSession(apps[0].exePath), true)
    assert.equal(assertExeExcludedInSession(apps[1].exePath), false)

    // БС: только Chrome через VPN → Edge мимо
    saveExclusionsState({ filePath, selectedIds: ['chrome'], apps, whitelist: true })
    const wlVpn = getExcludedExePathsForVpn(filePath)
    assert.ok(wlVpn.includes(apps[1].exePath))
    assert.ok(!wlVpn.includes(apps[0].exePath))

    void clearActiveExcludedExePaths()
    fs.rmSync(dir, { recursive: true, force: true })
  })
})

describe('collectYandexApps finds versioned browser.exe', () => {
  it('discovers Application\\browser.exe and Application\\x.y\\browser.exe under LOCALAPPDATA', () => {
    const { collectYandexApps } = require('../src/main/apps/listInstalledApps')
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'silent-yandex-'))
    const appDir = path.join(dir, 'Yandex', 'YandexBrowser', 'Application')
    const verDir = path.join(appDir, '25.6.1.1000')
    fs.mkdirSync(verDir, { recursive: true })
    const stub = Buffer.from('MZ') // minimal so existsSync passes; we don't execute
    const direct = path.join(appDir, 'browser.exe')
    const versioned = path.join(verDir, 'browser.exe')
    fs.writeFileSync(direct, stub)
    fs.writeFileSync(versioned, stub)

    const prev = process.env.LOCALAPPDATA
    process.env.LOCALAPPDATA = dir
    try {
      const found = collectYandexApps()
      const exes = found.map(a => String(a.exePath || '').toLowerCase().replace(/\//g, '\\'))
      assert.ok(exes.some(p => p.endsWith('\\browser.exe')), 'ожидался browser.exe')
      assert.ok(found.some(a => /яндекс браузер/i.test(a.name)))
    } finally {
      process.env.LOCALAPPDATA = prev
      fs.rmSync(dir, { recursive: true, force: true })
    }
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
    applyAppExclusionsForSession(exePaths, () => {}, { enableBypass: false })
    assert.equal(assertExeExcludedInSession(pick.exePath), true)
    void clearActiveExcludedExePaths()
  })
})

describe('VPN wiring in main.js', () => {
  it('main.js loads exclusion modules on connect path', () => {
    const mainSrc = fs.readFileSync(path.join(__dirname, '../src/main/main.js'), 'utf8')
    assert.match(mainSrc, /getExcludedExePathsForVpn/)
    assert.match(mainSrc, /applyAppExclusionsForSession/)
    assert.match(mainSrc, /save-app-exclusions/)
    assert.match(mainSrc, /clearActiveExcludedExePaths/)
    assert.match(mainSrc, /save-site-bypass/)
    assert.match(mainSrc, /applySiteBypassFromFile/)
  })
})
