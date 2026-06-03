import { activeServerHashCount, getSavedHashItems } from './hashItemsStore'

export const WORKERS_PER_GROUP = 9
export const MAX_WORKERS_PER_HASH = 27
export const MAX_HASHES = 4
export const LIBCLIENT_MAX_WORKERS = 108
export const DEFAULT_TOTAL_WORKERS = LIBCLIENT_MAX_WORKERS
export const BOOTSTRAP_STREAM_COUNT = 9

/** @deprecated legacy key — migrated to TOTAL_WORKERS_KEY */
export const CHANNELS_KEY = 'silent_hash_channels_per_hash'
export const TOTAL_WORKERS_KEY = 'silent_hash_total_workers'
export const LEGACY_MIGRATED_KEY = 'silent_hash_total_workers_legacy_migrated'

export function maxTotalWorkers(activeHashCount: number): number {
  return Math.min(Math.max(activeHashCount, 1), MAX_HASHES) * MAX_WORKERS_PER_HASH
}

export function normalizeTotalWorkers(value: number, activeHashCount: number): number {
  const max = maxTotalWorkers(activeHashCount)
  const stepped = Math.round(value / WORKERS_PER_GROUP) * WORKERS_PER_GROUP
  return Math.min(max, Math.max(WORKERS_PER_GROUP, stepped), LIBCLIENT_MAX_WORKERS)
}

/** Число групп libclient = n / 9 (до 12 групп = 108 воркеров). */
export function groupsForWorkers(totalWorkers: number): number {
  const maxGroups = LIBCLIENT_MAX_WORKERS / WORKERS_PER_GROUP
  return Math.min(
    Math.max(Math.floor(Math.max(totalWorkers, WORKERS_PER_GROUP) / WORKERS_PER_GROUP), 1),
    maxGroups,
  )
}

/** Таймаут connect: 60 с + ~25 с на каждую доп. группу (каскад + капча), макс. 3 мин. */
export function connectWaitTimeoutMs(totalWorkers: number): number {
  const groups = groupsForWorkers(totalWorkers)
  return Math.min(60_000 + Math.max(0, groups - 1) * 25_000, 180_000)
}

/**
 * Передаём libclient ВСЕ доступные хеши (до MAX_HASHES).
 * libclient сам распределяет воркеров по хешам циклически — как в proxy-turn-vk-android.
 */
export function hashesForLibclient(allHashes: string[], _totalWorkers: number): string[] {
  const unique = allHashes
    .flatMap(h => h.split(/[,\s\n]+/))
    .map(h => h.trim())
    .filter(h => h.length >= 6)
    .filter((h, i, arr) => arr.indexOf(h) === i)
  return unique.slice(0, MAX_HASHES)
}

export function migrateLegacyPerHash(oldPerHash: number, activeHashCount: number): number {
  const asTotal =
    oldPerHash <= 9 ? 9
      : oldPerHash <= 18 ? 18
        : oldPerHash <= 27 ? 27
          : oldPerHash <= 36 ? 36
            : oldPerHash <= 54 ? 54
              : oldPerHash <= 72 ? 72
                : DEFAULT_TOTAL_WORKERS
  return normalizeTotalWorkers(asTotal, activeHashCount)
}

export function getTotalWorkers(activeHashCount = activeServerHashCount(getSavedHashItems()) || 1): number {
  const capped = Math.min(Math.max(activeHashCount, 1), MAX_HASHES)
  const max = maxTotalWorkers(capped)
  const stored = localStorage.getItem(TOTAL_WORKERS_KEY)
  if (stored != null && stored !== '') {
    const raw = Number(stored) || WORKERS_PER_GROUP
    if (raw > max) {
      saveTotalWorkers(max, capped)
      return max
    }
    return normalizeTotalWorkers(raw, capped)
  }
  if (
    localStorage.getItem(LEGACY_MIGRATED_KEY) !== '1' &&
    localStorage.getItem(CHANNELS_KEY) != null &&
    localStorage.getItem(CHANNELS_KEY) !== ''
  ) {
    const legacyPer = Number(localStorage.getItem(CHANNELS_KEY)) || WORKERS_PER_GROUP
    const migrated = migrateLegacyPerHash(legacyPer, capped)
    localStorage.setItem(TOTAL_WORKERS_KEY, String(migrated))
    localStorage.setItem(LEGACY_MIGRATED_KEY, '1')
    return migrated
  }
  const firstInstall = normalizeTotalWorkers(WORKERS_PER_GROUP * 4, capped)
  saveTotalWorkers(firstInstall, capped)
  return firstInstall
}

export function saveTotalWorkers(value: number, activeHashCount = activeServerHashCount(getSavedHashItems()) || 1): void {
  localStorage.setItem(
    TOTAL_WORKERS_KEY,
    String(normalizeTotalWorkers(value, activeHashCount)),
  )
}

export function workersForLibclient(totalWorkers: number, activeHashCount: number): number {
  return normalizeTotalWorkers(totalWorkers, Math.min(Math.max(activeHashCount, 1), MAX_HASHES))
}

export function workersForHashSlot(totalWorkers: number, hashIndex: number, activeHashCount: number): number {
  if (hashIndex < 0 || hashIndex >= Math.max(activeHashCount, 1)) return 0
  const groups = groupsForWorkers(totalWorkers)
  if (groups <= 0) return 0
  let perHash = 0
  for (let i = 0; i < groups; i++) {
    if (i % activeHashCount === hashIndex) perHash += WORKERS_PER_GROUP
  }
  return Math.min(MAX_WORKERS_PER_HASH, perHash)
}

export function signalBars(activeWorkers: number, totalWorkers: number): number {
  const expected = normalizeTotalWorkers(totalWorkers, 1)
  if (expected <= 0) return 0
  const ratio = activeWorkers / expected
  if (ratio >= 0.85) return 4
  if (ratio >= 0.6) return 3
  if (ratio >= 0.35) return 2
  if (activeWorkers > 0) return 1
  return 0
}

function capHashes(hashes: string[] | undefined): string[] {
  return (hashes || [])
    .flatMap(h => h.split(/[,\s\n]+/))
    .map(h => h.trim())
    .filter(h => h.length >= 6)
    .filter((h, i, arr) => arr.indexOf(h) === i)
    .slice(0, MAX_HASHES)
}

export function resolveWorkerCount(config: { vk_hashes?: string[]; stream_count?: number }): number {
  const savedActive = activeServerHashCount(getSavedHashItems())
  const cappedHashes = capHashes(config.vk_hashes)
  const hashCount = Math.min(
    Math.max(cappedHashes.length, savedActive, 1),
    MAX_HASHES,
  )
  return workersForLibclient(getTotalWorkers(hashCount), hashCount)
}

export function applyBootstrapWorkerCount<T extends { vk_hashes?: string[]; stream_count?: number }>(
  config: T,
  bootHash?: string,
): T {
  const hash = (config.vk_hashes || []).map(h => h.trim()).filter(Boolean)[0]
    || bootHash?.trim()
    || ''
  const workers = config.stream_count ?? BOOTSTRAP_STREAM_COUNT
  return {
    ...config,
    vk_hashes: hash ? [hash] : config.vk_hashes,
    stream_count: Math.min(Math.max(workers, 3), 9),
  }
}

/** Один connect с полным n и всеми хешами (как Android wdttConnectConfig). */
export function applyWorkerCount<T extends { vk_hashes?: string[]; stream_count?: number }>(config: T): T {
  const cappedHashes = capHashes(config.vk_hashes)
  const workers = resolveWorkerCount({ ...config, vk_hashes: cappedHashes })
  const libclientHashes = hashesForLibclient(cappedHashes, workers)
  return {
    ...config,
    vk_hashes: libclientHashes.length > 0 ? libclientHashes : cappedHashes.slice(0, 1),
    stream_count: workers,
  }
}
