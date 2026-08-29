/**
 * Release-only целостность PC-клиента.
 * Debug / unpackaged (npm run dev) — проверки пропускаются.
 *
 * Хеш wdtt-client.exe генерируется scripts/gen_integrity_hashes.js
 * (вызывается из build-installer.bat после go build).
 */
const fs = require('fs')
const path = require('path')
const crypto = require('crypto')

let hashes
try {
  hashes = require('./integrityHashes')
} catch {
  hashes = { WDTT_SHA256: '', GENERATED_AT: '' }
}

function sha256File(filePath) {
  const hash = crypto.createHash('sha256')
  hash.update(fs.readFileSync(filePath))
  return hash.digest('hex')
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
    expectedSha != null
      ? expectedSha
      : (
        path.basename(String(exePath || '')) === 'wdtt-client'
          ? (hashes.WDTT_LINUX_SHA256 || hashes.WDTT_SHA256 || '')
          : (hashes.WDTT_SHA256 || '')
      ),
  ).trim().toLowerCase()
  if (!expected) {
    // Нет пина в сборке — не блокируем (старые/ручные пакеты), только warn
    log?.('[Integrity] WDTT_SHA256 пуст — пропуск проверки (пересоберите через build-installer.bat)')
    return { ok: true }
  }
  if (!exePath || !fs.existsSync(exePath)) {
    return { ok: false, reason: `${path.basename(exePath) || 'wdtt-client'} не найден. Переустановите Silent VPN.` }
  }
  try {
    const actual = sha256File(exePath)
    if (actual !== expected) {
      log?.(`[Integrity] wdtt-client hash mismatch`)
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
 * Soft: наличие/окружение подозрительно (не блокирует VPN).
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
}
