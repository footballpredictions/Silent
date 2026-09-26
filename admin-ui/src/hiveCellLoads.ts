/** Один пустой ответ опроса не стирает CPU/RAM/канал. Три подряд — уже недоступен. */

export function mergeHiveCellLoads<T extends { id: string; load?: unknown }>(
  prev: T[],
  next: T[],
  misses: Record<string, number>,
): { cells: T[]; misses: Record<string, number> } {
  const prevLoad = new Map(prev.map(cell => [cell.id, cell.load]))
  const nextMisses: Record<string, number> = {}
  const cells = next.map(cell => {
    if (cell.load) {
      return cell
    }
    const miss = (misses[cell.id] || 0) + 1
    nextMisses[cell.id] = miss
    const kept = prevLoad.get(cell.id)
    if (kept && miss < 3) {
      return { ...cell, load: kept }
    }
    return cell
  })
  return { cells, misses: nextMisses }
}
