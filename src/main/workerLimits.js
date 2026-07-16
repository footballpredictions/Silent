/** Лимиты воркеров для PC main / тестов. */
const WORKERS_PER_GROUP = 9

/**
 * Авто/ручная капча (vk-auth-mode=legacy) — запасной режим: одна группа.
 * VK Calls держит полный n (обычно 63).
 */
function effectiveConnectWorkers({ isBootstrap, vkAuthMode, streamCount }) {
  const n = Math.min(Math.max(Number(streamCount) || WORKERS_PER_GROUP, WORKERS_PER_GROUP), 108)
  if (isBootstrap) return Math.min(Math.max(Number(streamCount) || 3, 3), 108)
  if (String(vkAuthMode || '').trim().toLowerCase() === 'legacy') {
    return WORKERS_PER_GROUP
  }
  return n
}

module.exports = {
  WORKERS_PER_GROUP,
  effectiveConnectWorkers,
}
