/** VK bootstrap-хеш, зашитый при сборке (debug — фиксированный, release — BOOTSTRAP_VK_HASH). */
declare const __BOOTSTRAP_VK_HASH__: string

export function getEmbeddedBootstrapHash(): string {
  return __BOOTSTRAP_VK_HASH__
}
