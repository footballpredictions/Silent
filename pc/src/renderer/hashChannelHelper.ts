import { activeServerHashCount, getSavedHashItems } from './hashItemsStore'

export const CHANNEL_OPTIONS = [9, 18, 27] as const
export const CHANNELS_KEY = 'silent_hash_channels_per_hash'
export const MAX_HASHES = 4

export function normalizeChannelsPerHash(value: number): number {
  if (value <= 9) return 9
  if (value <= 18) return 18
  return 27
}

export function getChannelsPerHash(): number {
  const raw = Number(localStorage.getItem(CHANNELS_KEY) || 9)
  return normalizeChannelsPerHash(raw)
}

export function saveChannelsPerHash(value: number): void {
  localStorage.setItem(CHANNELS_KEY, String(normalizeChannelsPerHash(value)))
}

export function computeWorkerCount(activeHashCount: number, channelsPerHash: number): number {
  const hashes = Math.min(Math.max(activeHashCount, 1), MAX_HASHES)
  const per = normalizeChannelsPerHash(channelsPerHash)
  return Math.min(128, Math.max(3, hashes * per))
}

export function signalBars(activeChannelsOnHash: number, channelsPerHash: number): number {
  const expected = normalizeChannelsPerHash(channelsPerHash)
  if (expected <= 0) return 0
  const ratio = activeChannelsOnHash / expected
  if (ratio >= 0.85) return 4
  if (ratio >= 0.6) return 3
  if (ratio >= 0.35) return 2
  if (activeChannelsOnHash > 0) return 1
  return 0
}

export function resolveWorkerCount(config: { vk_hashes?: string[]; stream_count?: number }): number {
  const savedActive = activeServerHashCount(getSavedHashItems())
  const hashCount = Math.max(
    config.vk_hashes?.filter(h => h?.trim()).length || 0,
    savedActive,
    1,
  )
  const userWorkers = computeWorkerCount(hashCount, getChannelsPerHash())
  return Math.max(userWorkers, config.stream_count || 0)
}

export function applyWorkerCount<T extends { vk_hashes?: string[]; stream_count?: number }>(config: T): T {
  return { ...config, stream_count: resolveWorkerCount(config) }
}
