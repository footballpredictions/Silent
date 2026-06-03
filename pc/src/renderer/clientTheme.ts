/** Client theme from admin panel (/api/vpn/theme) — same fields as MainScreen. */
export interface ClientTheme {
  background_color?: string
  text_color?: string
  toggle_on_color?: string
  toggle_off_color?: string
  font_family?: string
  app_name?: string
}

function parseHex(color: string): { r: number; g: number; b: number } | null {
  const h = color.replace('#', '').trim()
  if (h.length !== 6) return null
  const n = parseInt(h, 16)
  if (Number.isNaN(n)) return null
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 }
}

function isDarkBg(bg: string): boolean {
  const rgb = parseHex(bg)
  if (!rgb) return false
  const lum = (0.299 * rgb.r + 0.587 * rgb.g + 0.114 * rgb.b) / 255
  return lum < 0.45
}

export function resolveAppName(raw?: string | null): string {
  const name = (raw || '').trim()
  if (!name || name.toLowerCase() === 'silent') return 'Silent VPN'
  return name
}

/** UI palette derived from admin theme (login + main screens). */
export function themeToUi(theme: ClientTheme | null) {
  const bg = theme?.background_color || '#ffffff'
  const fg = theme?.text_color || '#000000'
  const dark = isDarkBg(bg)
  const muted = `${fg}99`
  return {
    bg,
    fg,
    muted,
    dark,
    fieldBg: dark ? '#161616' : '#f3f4f6',
    fieldText: fg,
    fieldPlaceholder: dark ? '#9CA3AF' : '#6B7280',
    label: dark ? '#D1D5DB' : '#374151',
    hint: dark ? '#9CA3AF' : '#6B7280',
    border: dark ? '#374151' : '#e5e7eb',
    tabBg: dark ? '#1F1F1F' : '#f3f4f6',
    divider: dark ? '#2A2A2A' : '#e5e7eb',
    headerBg: dark ? '#000000' : bg,
    headerFg: dark ? '#9CA3AF' : muted,
    primaryBtnBg: dark ? '#ffffff' : fg,
    primaryBtnFg: dark ? '#000000' : bg,
    green: '#16A34A',
    red: '#EF4444',
    fontFamily: theme?.font_family ? `${theme.font_family}, Inter, sans-serif` : 'Inter, sans-serif',
    appTitle: resolveAppName(theme?.app_name).toUpperCase(),
  }
}
