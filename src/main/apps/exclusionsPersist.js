/**
 * Чистое состояние исключений: два списка + режим.
 * Смена режима не трогает другой список. Старый формат (один selectedIds) мигрирует.
 */

function asIdList(value) {
  if (value instanceof Set) return [...value].map(String).filter(Boolean)
  if (!Array.isArray(value)) return []
  return value.map(String).filter(Boolean)
}

function uniqueIds(ids) {
  return [...new Set(asIdList(ids))]
}

/**
 * @param {{ selectedIds?: string[], whitelist?: boolean, blacklistAppIds?: string[]|null, whitelistAppIds?: string[]|null }} raw
 */
function hydrateExclusions(raw = {}) {
  const whitelist = !!raw.whitelist
  const hasDual =
    raw.blacklistAppIds != null || raw.whitelistAppIds != null
  if (hasDual) {
    return {
      whitelist,
      appBypassMode: whitelist ? 'whitelist' : 'blacklist',
      blacklistAppIds: uniqueIds(raw.blacklistAppIds),
      whitelistAppIds: uniqueIds(raw.whitelistAppIds),
    }
  }
  const selected = uniqueIds(raw.selectedIds)
  if (whitelist) {
    return {
      whitelist: true,
      appBypassMode: 'whitelist',
      blacklistAppIds: [],
      whitelistAppIds: selected,
    }
  }
  return {
    whitelist: false,
    appBypassMode: 'blacklist',
    blacklistAppIds: selected,
    whitelistAppIds: [],
  }
}

function switchExclusionsMode(state, toWhitelist) {
  const next = !!toWhitelist
  return {
    ...state,
    whitelist: next,
    appBypassMode: next ? 'whitelist' : 'blacklist',
    blacklistAppIds: uniqueIds(state.blacklistAppIds),
    whitelistAppIds: uniqueIds(state.whitelistAppIds),
  }
}

function setActiveIds(state, ids) {
  const list = uniqueIds(ids)
  if (state.whitelist) {
    return { ...state, whitelistAppIds: list }
  }
  return { ...state, blacklistAppIds: list }
}

function activeIds(state) {
  return state.whitelist ? uniqueIds(state.whitelistAppIds) : uniqueIds(state.blacklistAppIds)
}

/**
 * Слияние сохранения: выбранный режим + активный список; другой список из prev.
 * Если пришли оба массива — они source of truth.
 */
function applySave(prevRaw, { selectedIds, whitelist, blacklistAppIds, whitelistAppIds }) {
  const prev = hydrateExclusions(prevRaw || {})
  let next
  if (blacklistAppIds != null || whitelistAppIds != null) {
    next = hydrateExclusions({
      whitelist,
      blacklistAppIds: blacklistAppIds != null ? blacklistAppIds : prev.blacklistAppIds,
      whitelistAppIds: whitelistAppIds != null ? whitelistAppIds : prev.whitelistAppIds,
    })
    if (selectedIds != null) next = setActiveIds(next, selectedIds)
    return next
  }
  return setActiveIds(switchExclusionsMode(prev, !!whitelist), selectedIds || [])
}

module.exports = {
  asIdList,
  uniqueIds,
  hydrateExclusions,
  switchExclusionsMode,
  setActiveIds,
  activeIds,
  applySave,
}
