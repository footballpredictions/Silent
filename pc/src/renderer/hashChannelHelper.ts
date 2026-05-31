import { activeServerHashCount, getSavedHashItems } from './hashItemsStore'

export const WORKERS_PER_GROUP = 9
export const MAX_WORKERS_PER_HASH = 9
export const DEFAULT_TOTAL_WORKERS = 18
export const MAX_HASHES = 2
export const LIBCLIENT_MAX_WORKERS = 18
export const BOOTSTRAP_STREAM_COUNT = 3

/** @deprecated legacy key — migrated to TOTAL_WORKERS_KEY */
export const CHANNELS_KEY = 'silent_hash_channels_per_hash'
export const TOTAL_WORKERS_KEY = 'silent_hash_total_workers'

export function maxTotalWorkers(activeHashCount: number): number {
  return Math.min(Math.max(activeHashCount, 1), MAX_HASHES) * MAX_WORKERS_PER_HASH
}

export function normalizeTotalWorkers(value: number, activeHashCount: number): number {
  const max = maxTotalWorkers(activeHashCount)
  const stepped = Math.round(value / WORKERS_PER_GROUP) * WORKERS_PER_GROUP
  return Math.min(max, Math.max(WORKERS_PER_GROUP, stepped), LIBCLIENT_MAX_WORKERS)
}

/** Число групп libclient = n / 9. */
export function groupsForWorkers(totalWorkers: number): number {
  return Math.min(
    Math.max(Math.floor(Math.max(totalWorkers, WORKERS_PER_GROUP) / WORKERS_PER_GROUP), 1),
    MAX_HASHES,
  )
}

/**
 * Только нужное число хешей для `-vk`: при n=18 — 2 хеша, не все слоты сразу.
 */
export function hashesForLibclient(allHashes: string[], totalWorkers: number): string[] {
  const unique = allHashes
    .flatMap(h => h.split(/[,\s\n]+/))
    .map(h => h.trim())
    .filter(h => h.length >= 6)
    .filter((h, i, arr) => arr.indexOf(h) === i)
  if (unique.length === 0) return []
  const groups = groupsForWorkers(
    workersForLibclient(totalWorkers, Math.min(unique.length, MAX_HASHES)),
  )
  return unique.slice(0, groups)
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
  const stored = localStorage.getItem(TOTAL_WORKERS_KEY)
  if (stored != null && stored !== '') {
    const raw = Number(stored) || DEFAULT_TOTAL_WORKERS
    if (raw > maxTotalWorkers(capped)) {
      const fixed = normalizeTotalWorkers(DEFAULT_TOTAL_WORKERS, capped)
      saveTotalWorkers(fixed, capped)
      return fixed
    }
    return normalizeTotalWorkers(raw, capped)
  }
  const legacy = Number(localStorage.getItem(CHANNELS_KEY) || DEFAULT_TOTAL_WORKERS)
  const migrated = migrateLegacyPerHash(legacy, capped)
  saveTotalWorkers(migrated, capped)
  return migrated
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
