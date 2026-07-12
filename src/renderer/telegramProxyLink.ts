/** Open installed Telegram Desktop for MTProto proxy (not the download website). */
export function telegramProxyDeepLink(raw: string): string {
  const url = (raw || '').trim()
  if (!url) return url
  if (/^tg:\/\/proxy\b/i.test(url)) return url
  // https://t.me/proxy?server=…&port=…&secret=… → tg://proxy?…
  const m = url.match(/^https?:\/\/t\.me\/proxy\?(.*)$/i)
  if (m) return `tg://proxy?${m[1]}`
  return url
}
