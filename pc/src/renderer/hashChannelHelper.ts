import { activeServerHashCount, getSavedHashItems } from './hashItemsStore'

export const WORKERS_PER_GROUP = 9
export const MAX_WORKERS_PER_HASH = 27
export const DEFAULT_TOTAL_WORKERS = 18
export const MAX_HASHES = 4

/** @deprecated legacy key — migrated to TOTAL_WORKERS_KEY */
export const CHANNELS_KEY = 'silent_hash_channels_per_hash'
export const TOTAL_WORKERS_KEY = 'silent_hash_total_workers'

export function maxTotalWorkers(activeHashCount: number): number {
  return Math.min(Math.max(activeHashCount, 1), MAX_HASHES) * MAX_WORKERS_PER_HASH
}

export function normalizeTotalWorkers(value: number, activeHashCount: number): number {
  const max = maxTotalWorkers(activeHashCount)
  const stepped = Math.round(value / WORKERS_PER_GROUP) * WORKERS_PER_GROUP
  return Math.min(max, Math.max(WORKERS_PER_GROUP, stepped))
}

export function migrateLegacyPerHash(oldPerHash: number, activeHashCount: number): number {
  const per = oldPerHash <= 9 ? 9 : oldPerHash <= 18 ? 18 : 27
  return normalizeTotalWorkers(per * Math.max(activeHashCount, 1), activeHashCount)
}

export function getTotalWorkers(activeHashCount = activeServerHashCount(getSavedHashItems()) || 1): number {
  const stored = localStorage.getItem(TOTAL_WORKERS_KEY)
  if (stored != null && stored !== '') {
    return normalizeTotalWorkers(Number(stored) || DEFAULT_TOTAL_WORKERS, activeHashCount)
  }
  const legacy = Number(localStorage.getItem(CHANNELS_KEY) || DEFAULT_TOTAL_WORKERS)
  const migrated = migrateLegacyPerHash(legacy, activeHashCount)
  saveTotalWorkers(migrated, activeHashCount)
  return migrated
}

export function saveTotalWorkers(value: number, activeHashCount = activeServerHashCount(getSavedHashItems()) || 1): void {
  localStorage.setItem(
    TOTAL_WORKERS_KEY,
    String(normalizeTotalWorkers(value, activeHashCount)),
  )
}

export function workersForLibclient(totalWorkers: number, activeHashCount: number): number {
  return normalizeTotalWorkers(totalWorkers, activeHashCount)
}

export function workersForHashSlot(totalWorkers: number, hashIndex: number, activeHashCount: number): number {
  if (hashIndex < 0 || hashIndex >= Math.max(activeHashCount, 1)) return 0
  const groups = Math.floor(totalWorkers / WORKERS_PER_GROUP)
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

export function resolveWorkerCount(config: { vk_hashes?: string[]; stream_count?: number }): number {
  const savedActive = activeServerHashCount(getSavedHashItems())
  const hashCount = Math.min(
    Math.max(config.vk_hashes?.filter(h => h?.trim()).length || 0, savedActive, 1),
    MAX_HASHES,
  )
  return workersForLibclient(getTotalWorkers(hashCount), hashCount)
}

export function applyWorkerCount<T extends { vk_hashes?: string[]; stream_count?: number }>(config: T): T {
  return { ...config, stream_count: resolveWorkerCount(config) }
}
