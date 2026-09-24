/**
 * Release-only целостность PC-клиента.
 * Debug / unpackaged (npm run dev) — проверки пропускаются.
 *
 * Хеш wdtt-client генерируется scripts/gen_integrity_hashes.js
 * (Windows / Linux / Mac — разные поля).
 */
const fs = require('fs')
const path = require('path')
const crypto = require('crypto')

let hashes
try {
  hashes = require('./integrityHashes')
} catch {
  hashes = { WDTT_SHA256: '', WDTT_LINUX_SHA256: '', WDTT_MAC_SHA256: '', GENERATED_AT: '' }
}

function sha256File(filePath) {
  const hash = crypto.createHash('sha256')
  hash.update(fs.readFileSync(filePath))
  return hash.digest('hex')
}

/** Пин хеша по платформе (Mac и Linux оба зовутся wdtt-client — не путать). */
function resolveExpectedWdttSha(platform, pinHashes) {
  const h = pinHashes || {}
  if (platform === 'darwin') return String(h.WDTT_MAC_SHA256 || '').trim()
  if (platform === 'linux') return String(h.WDTT_LINUX_SHA256 || '').trim()
  return String(h.WDTT_SHA256 || '').trim()
}

/**
 * @param {{ isPackaged: boolean, isDebugBuild: boolean, exePath: string, log?: (s: string) => void, expectedSha?: string }} opts
 * @returns {{ ok: boolean, reason?: string }}
 */
function verifyWdttIntegrity({ isPackaged, isDebugBuild, exePath, log, expectedSha }) {
  if (!isPackaged || isDebugBuild) {
    return { ok: true }
  }
  const expected = String(
    expectedSha != null ? expectedSha : resolveExpectedWdttSha(process.platform, hashes),
  )
    .trim()
    .toLowerCase()
  if (!expected) {
    // Нет пина в сборке — не блокируем (старые/ручные пакеты), только warn
    log?.('[Integrity] WDTT SHA пуст — пропуск проверки (пересоберите через build-*.sh/bat)')
    return { ok: true }
  }
  if (!exePath || !fs.existsSync(exePath)) {
    return { ok: false, reason: `${path.basename(exePath) || 'wdtt-client'} не найден. Переустановите Silent VPN.` }
  }
  try {
    const actual = sha256File(exePath)
    if (actual !== expected) {
      log?.(`[Integrity] wdtt-client hash mismatch (platform=${process.platform})`)
      return {
        ok: false,
        reason:
          'VPN-модуль изменён или повреждён. Установите Silent VPN с официального сайта.',
      }
    }
  } catch (e) {
    return { ok: false, reason: `Ошибка проверки сборки: ${e?.message || e}` }
  }
  return { ok: true }
}

/**
 * Soft: файл/окружение подозрительно (не блокирует VPN).
 */
function softTamperHints({ isPackaged, isDebugBuild, log }) {
  if (!isPackaged || isDebugBuild) return
  try {
    // ELECTRON_RUN_AS_NODE / unpack asar — типичные признаки патча
    if (process.env.ELECTRON_RUN_AS_NODE === '1') {
      log?.('[Integrity] warn: ELECTRON_RUN_AS_NODE=1')
    }
    const resources = process.resourcesPath || ''
    const asarPath = path.join(resources, 'app.asar')
    const unpackedMain = path.join(resources, 'app', 'src', 'main', 'main.js')
    if (!fs.existsSync(asarPath) && fs.existsSync(unpackedMain)) {
      log?.('[Integrity] warn: app.asar отсутствует, main из unpacked app/')
    }
  } catch {
    /* ignore */
  }
}

module.exports = {
  verifyWdttIntegrity,
  softTamperHints,
  sha256File,
  resolveExpectedWdttSha,
}
