import { isDebugBuild } from './debugBuild'

const KEY = 'vk_cred_strategy'

export const VK_CRED_VKCALLS = 'vkcalls'
export const VK_CRED_AUTO = 'auto'
export const VK_CRED_MANUAL = 'manual'

export interface VkCredLaunchParams {
  captchaMode: string
  vkAuthMode: string
}

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

export function vkCredStrategyLabel(strategy: string = getVkCredStrategy()): string {
  switch (strategy) {
    case VK_CRED_AUTO: return 'Авто капча'
    case VK_CRED_MANUAL: return 'Ручная'
    default: return 'VKCalls'
  }
}

export function resolveVkCredLaunchParams(): VkCredLaunchParams {
  switch (getVkCredStrategy()) {
    case VK_CRED_AUTO:
      return { vkAuthMode: 'legacy', captchaMode: 'auto' }
    case VK_CRED_MANUAL:
      return { vkAuthMode: 'legacy', captchaMode: 'manual' }
    default:
      return { vkAuthMode: 'vkcalls', captchaMode: 'auto' }
  }
}

/** Авто/ручная — запасной путь с капчей (не основной VK Calls). */
export function isLegacyCaptchaStrategy(strategy: string = getVkCredStrategy()): boolean {
  return strategy === VK_CRED_AUTO || strategy === VK_CRED_MANUAL
}

export function attachVkCredLaunchParams<T extends Record<string, unknown>>(config: T): T & VkCredLaunchParams {
  const p = resolveVkCredLaunchParams()
  return { ...config, captchaMode: p.captchaMode, vkAuthMode: p.vkAuthMode }
}
