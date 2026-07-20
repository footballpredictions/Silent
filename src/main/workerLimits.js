/** Лимиты воркеров для PC main / тестов. */
const WORKERS_PER_GROUP = 9
/**
 * Legacy/captcha: boot = 1 группа (без шторма капчи), затем рамп до 27.
 * Иначе full tunnel @9 → YouTube без WDTT-полосы (см. 2026-07-09).
 */
const LEGACY_CAPTCHA_TARGET_WORKERS = 27

/**
 * Авто/ручная капча (vk-auth-mode=legacy) — целевой n после рампа.
 * VK Calls держит полный n (обычно 63). Boot для legacy — отдельно в main.js (=9).
 */
function effectiveConnectWorkers({ isBootstrap, vkAuthMode, streamCount }) {
  const n = Math.min(Math.max(Number(streamCount) || WORKERS_PER_GROUP, WORKERS_PER_GROUP), 108)
  if (isBootstrap) return Math.min(Math.max(Number(streamCount) || 3, 3), 108)
  if (String(vkAuthMode || '').trim().toLowerCase() === 'legacy') {
    return Math.min(LEGACY_CAPTCHA_TARGET_WORKERS, n)
  }
  return n
}

module.exports = {
  WORKERS_PER_GROUP,
  LEGACY_CAPTCHA_TARGET_WORKERS,
  effectiveConnectWorkers,
}
