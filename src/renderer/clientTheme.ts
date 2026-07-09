/** Client theme from admin panel (/api/vpn/theme) — same fields as MainScreen. */
export interface ClientTheme {
  primary_color?: string
  background_color?: string
  text_color?: string
  accent_color?: string
  toggle_on_color?: string
  toggle_off_color?: string
  font_family?: string
  app_name?: string
  update_bar_background_color?: string
  update_bar_text_color?: string
  update_bar_progress_color?: string
  update_bar_label_available?: string
  update_bar_label_downloading?: string
  dark_primary_color?: string
  dark_background_color?: string
  dark_text_color?: string
  dark_accent_color?: string
  dark_toggle_on_color?: string
  dark_toggle_off_color?: string
  dark_update_bar_background_color?: string
  dark_update_bar_text_color?: string
  dark_update_bar_progress_color?: string
  dark_login_link_color?: string
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

function toHex(r: number, g: number, b: number): string {
  const c = (n: number) => Math.max(0, Math.min(255, Math.round(n))).toString(16).padStart(2, '0')
  return `#${c(r)}${c(g)}${c(b)}`
}

function luminance(hex: string): number {
  const rgb = parseHex(hex)
  if (!rgb) return 0.5
  return (0.299 * rgb.r + 0.587 * rgb.g + 0.114 * rgb.b) / 255
}

export function isDarkBg(bg: string): boolean {
  return luminance(bg) < 0.45
}

function invertHex(hex: string, fallback: string): string {
  const rgb = parseHex(hex)
  if (!rgb) return fallback
  return toHex(255 - rgb.r, 255 - rgb.g, 255 - rgb.b)
}

function pick(darkVal: string | undefined, lightVal: string, invertedFallback: string, wantDark: boolean): string {
  if (!wantDark) return lightVal
  const d = (darkVal || '').trim()
  if (d) return d
  return invertedFallback
}

/** Soften mid-luminance brand colors on dark bg for readability (neon glow hint). */
export function needsNeonGlow(hex: string, darkSurface: boolean): boolean {
  if (!darkSurface) return false
  const lum = luminance(hex)
  return lum > 0.18 && lum < 0.72
}

export function neonTextShadow(hex: string): string {
  return `0 0 8px ${hex}99, 0 0 18px ${hex}55`
}

export function resolveAppName(raw?: string | null): string {
  const name = (raw || '').trim()
  if (!name || name.toLowerCase() === 'silent') return 'Silent VPN'
  return name
}

export type AppearanceMode = 'light' | 'dark'

/** Effective palette for light/dark user toggle. */
export function resolveThemePalette(theme: ClientTheme | null, mode: AppearanceMode) {
  const wantDark = mode === 'dark'
  const lightBg = theme?.background_color || '#ffffff'
  const lightFg = theme?.text_color || '#000000'
  const lightPrimary = theme?.primary_color || lightFg
  const lightAccent = theme?.accent_color || '#1A1A1A'
  const lightToggleOn = theme?.toggle_on_color || '#000000'
  const lightToggleOff = theme?.toggle_off_color || '#cccccc'
  const lightUpdateBg = theme?.update_bar_background_color || '#2563EB'
  const lightUpdateFg = theme?.update_bar_text_color || '#FFFFFF'
  const lightUpdateProgress = theme?.update_bar_progress_color || '#1D4ED8'
  const lightLink = theme?.login_link_color || '#4680C2'

  const bg = pick(theme?.dark_background_color, lightBg, '#0B0B0F', wantDark)
  const fg = pick(theme?.dark_text_color, lightFg, '#F5F5F7', wantDark)
  const primary = pick(theme?.dark_primary_color, lightPrimary, invertHex(lightPrimary, '#FFFFFF'), wantDark)
  const accent = pick(theme?.dark_accent_color, lightAccent, invertHex(lightAccent, '#E5E7EB'), wantDark)
  const toggleOn = pick(theme?.dark_toggle_on_color, lightToggleOn, '#FFFFFF', wantDark)
  const toggleOff = pick(theme?.dark_toggle_off_color, lightToggleOff, '#3F3F46', wantDark)
  const updateBarBg = pick(theme?.dark_update_bar_background_color, lightUpdateBg, lightUpdateBg, wantDark)
  const updateBarFg = pick(theme?.dark_update_bar_text_color, lightUpdateFg, lightUpdateFg, wantDark)
  const updateBarProgress = pick(
    theme?.dark_update_bar_progress_color,
    lightUpdateProgress,
    lightUpdateProgress,
    wantDark,
  )
  const linkColor = pick(theme?.dark_login_link_color, lightLink, '#7DD3FC', wantDark)

  const dark = isDarkBg(bg)
  const muted = dark ? `${fg}B3` : `${fg}99`
  const border = dark ? '#2A2A32' : '#F3F4F6'
  const borderStrong = dark ? '#3F3F46' : '#E5E7EB'
  const surface = dark ? '#14141A' : '#F3F4F6'

  return {
    bg,
    fg,
    muted,
    dark,
    primary,
    accent,
    toggleOn,
    toggleOff,
    updateBarBg,
    updateBarFg,
    updateBarProgress,
    linkColor,
    border,
    borderStrong,
    surface,
    fieldBg: dark ? '#16161C' : '#f3f4f6',
    fieldText: fg,
    fieldPlaceholder: dark ? '#9CA3AF' : '#6B7280',
    label: dark ? '#D1D5DB' : '#374151',
    hint: dark ? '#9CA3AF' : '#6B7280',
    tabBg: dark ? '#1F1F26' : '#f3f4f6',
    divider: dark ? '#2A2A32' : '#e5e7eb',
    headerBg: dark ? '#000000' : bg,
    headerFg: dark ? '#9CA3AF' : muted,
    primaryBtnBg: dark ? '#ffffff' : fg,
    primaryBtnFg: dark ? '#000000' : bg,
    green: dark ? '#4ADE80' : '#16A34A',
    red: '#EF4444',
    purple: dark ? '#C084FC' : '#9333EA',
    fontFamily: theme?.font_family ? `${theme.font_family}, Inter, sans-serif` : 'Inter, sans-serif',
    appTitle: resolveAppName(theme?.app_name).toUpperCase(),
  }
}

/** UI palette derived from admin theme (login + main screens). Respects appearance mode. */
export function themeToUi(theme: ClientTheme | null, mode: AppearanceMode = 'light') {
  const p = resolveThemePalette(theme, mode)
  return {
    bg: p.bg,
    fg: p.fg,
    muted: p.muted,
    dark: p.dark,
    fieldBg: p.fieldBg,
    fieldText: p.fieldText,
    fieldPlaceholder: p.fieldPlaceholder,
    label: p.label,
    hint: p.hint,
    border: p.borderStrong,
    tabBg: p.tabBg,
    divider: p.divider,
    headerBg: p.headerBg,
    headerFg: p.headerFg,
    primaryBtnBg: p.primaryBtnBg,
    primaryBtnFg: p.primaryBtnFg,
    green: p.green,
    red: p.red,
    fontFamily: p.fontFamily,
    appTitle: p.appTitle,
    linkColor: p.linkColor,
  }
}
