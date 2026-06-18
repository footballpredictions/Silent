/** UI tokens — синхронизированы с Android `UiTokens.kt`. */
export const APP_WIDTH_PX = 265
export const MENU_WIDTH_PX = 208

/** Явная ширина drawer (Tailwind w-52 из константы не попадает в purge). */
export const menuDrawerStyle = {
  width: MENU_WIDTH_PX,
  minWidth: MENU_WIDTH_PX,
  maxWidth: MENU_WIDTH_PX,
  flexShrink: 0,
} as const

export const UI_COLORS = {
  gray100: '#F3F4F6',
  gray200: '#E5E7EB',
  red500: '#EF4444',
} as const
