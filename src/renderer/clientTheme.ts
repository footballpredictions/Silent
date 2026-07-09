/** Client theme from admin panel (/api/vpn/theme) — same fields as MainScreen. */
export interface ClientTheme {
  background_color?: string
  text_color?: string
  toggle_on_color?: string
  toggle_off_color?: string
  font_family?: string
  app_name?: string
  update_bar_background_color?: string
  update_bar_text_color?: string
  update_bar_progress_color?: string
  update_bar_label_available?: string
  update_bar_label_downloading?: string
  login_step1_title?: string
  login_step1_instruction?: string
  login_hash_placeholder?: string
  login_hash_button_text?: string
  login_vk_mobile_url?: string
  login_vk_mobile_link_text?: string
  login_vk_pc_url?: string
  login_vk_pc_link_text?: string
  login_link_color?: string
  login_step2_title?: string
  login_remember_me_label?: string
  login_forgot_password_label?: string
  login_forgot_title?: string
  login_forgot_instruction?: string
  login_reset_title?: string
  login_reset_button_text?: string
  support_url?: string
  telegram_channel_url?: string
  hive_standby_api_urls?: string
  menu_bonuses_label?: string
  bonuses_title?: string
  bonuses_intro_text?: string
  bonuses_referral_title?: string
  bonuses_referral_hint?: string
  bonuses_promo_title?: string
  bonuses_promo_hint?: string
  bonuses_rules_text?: string
  bonuses_copy_link_label?: string
  bonuses_copy_code_label?: string
  register_referral_or_promo_label?: string
  register_referral_or_promo_hint?: string
}

export function standbyApiBasesFromTheme(theme: ClientTheme | null): string[] {
  const raw = (theme?.hive_standby_api_urls || '').trim()
  if (!raw) return []
  return raw.split(',').map(s => s.trim()).filter(Boolean)
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
    linkColor: theme?.login_link_color || '#4680C2',
  }
}
