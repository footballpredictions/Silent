/** Тихий период после поднятия WG — не писать в лог транзиентные Network Error. */
let settlingUntilMs = 0

export function markVpnApiSettling(durationMs = 90_000): void {
  settlingUntilMs = Date.now() + durationMs
}

export function isVpnApiSettling(): boolean {
  return Date.now() < settlingUntilMs
}

export function isTransientApiError(msg: string): boolean {
  return /network error|timeout|econnrefused|enotfound|aborted|exceeded/i.test(msg)
}
