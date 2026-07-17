import { isDebugBuild } from './debugBuild'

const KEY = 'vk_cred_strategy'

export const VK_CRED_VKCALLS = 'vkcalls'
export const VK_CRED_AUTO = 'auto'
export const VK_CRED_MANUAL = 'manual'

export interface VkCredLaunchParams {
  captchaMode: string
  vkAuthMode: string
}

/**
 * Эфемерный каскад на сессию подключения (не пишется в меню):
 * 0 = базовый режим, 1 = авто-капча, 2 = ручная.
 * Нужен когда VK Calls ловит Flood control — Go намеренно не падает в legacy
 * внутри процесса (шторм капчи), хост перезапускает libclient с n=9.
 */
let sessionEscalateLevel = 0

export function getVkCredStrategy(): string {
  if (!isDebugBuild) return VK_CRED_VKCALLS
  try {
    const stored = localStorage.getItem(KEY)
    if (stored === VK_CRED_AUTO || stored === VK_CRED_MANUAL) return stored
  } catch { /* ignore */ }
  return VK_CRED_VKCALLS
}

export function setVkCredStrategy(strategy: string) {
  const normalized =
    strategy === VK_CRED_AUTO || strategy === VK_CRED_MANUAL ? strategy : VK_CRED_VKCALLS
  localStorage.setItem(KEY, normalized)
}

/** Базовый + session escalate (для connect/bootstrap). */
export function getEffectiveVkCredStrategy(): string {
  const base = getVkCredStrategy()
  if (sessionEscalateLevel >= 2) return VK_CRED_MANUAL
  if (sessionEscalateLevel >= 1) {
    return base === VK_CRED_MANUAL ? VK_CRED_MANUAL : VK_CRED_AUTO
  }
  return base
}

export function resetVkCredSessionEscalate() {
  sessionEscalateLevel = 0
}

export function getVkCredSessionEscalateLevel(): number {
  return sessionEscalateLevel
}

/** Поднять на один шаг: vkcalls→auto→manual. false = уже на максимуме. */
export function escalateVkCredSession(): boolean {
  const current = getEffectiveVkCredStrategy()
  if (current === VK_CRED_MANUAL) return false
  if (current === VK_CRED_AUTO) {
    sessionEscalateLevel = Math.max(sessionEscalateLevel, 2)
    return true
  }
  // vkcalls
  if (sessionEscalateLevel < 1) {
    sessionEscalateLevel = 1
    return true
  }
  if (sessionEscalateLevel < 2) {
    sessionEscalateLevel = 2
    return true
  }
  return false
}

export function vkCredStrategyLabel(strategy: string = getEffectiveVkCredStrategy()): string {
  switch (strategy) {
    case VK_CRED_AUTO: return 'Авто капча'
    case VK_CRED_MANUAL: return 'Ручная'
    default: return 'VKCalls'
  }
}

export function resolveVkCredLaunchParams(): VkCredLaunchParams {
  switch (getEffectiveVkCredStrategy()) {
    case VK_CRED_AUTO:
      return { vkAuthMode: 'legacy', captchaMode: 'auto' }
    case VK_CRED_MANUAL:
      return { vkAuthMode: 'legacy', captchaMode: 'manual' }
    default:
      return { vkAuthMode: 'vkcalls', captchaMode: 'auto' }
  }
}

/** Авто/ручная — запасной путь с капчей (не основной VK Calls). */
export function isLegacyCaptchaStrategy(strategy: string = getEffectiveVkCredStrategy()): boolean {
  return strategy === VK_CRED_AUTO || strategy === VK_CRED_MANUAL
}

export function attachVkCredLaunchParams<T extends Record<string, unknown>>(config: T): T & VkCredLaunchParams {
  const p = resolveVkCredLaunchParams()
  return { ...config, captchaMode: p.captchaMode, vkAuthMode: p.vkAuthMode }
}
