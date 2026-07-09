import { useCallback, useEffect, useState } from 'react'
import type { AppearanceMode } from './clientTheme'

const KEY = 'silent_appearance_mode'

function readMode(): AppearanceMode {
  try {
    const v = localStorage.getItem(KEY)
    if (v === 'dark' || v === 'light') return v
  } catch { /* ignore */ }
  return 'light'
}

let current: AppearanceMode = readMode()
const listeners = new Set<(m: AppearanceMode) => void>()

function emit(mode: AppearanceMode) {
  current = mode
  listeners.forEach(l => l(mode))
}

export function getAppearanceMode(): AppearanceMode {
  return current
}

export function setAppearanceMode(mode: AppearanceMode) {
  try {
    localStorage.setItem(KEY, mode)
  } catch { /* ignore */ }
  emit(mode)
}

export function toggleAppearanceMode(): AppearanceMode {
  const next: AppearanceMode = current === 'dark' ? 'light' : 'dark'
  setAppearanceMode(next)
  return next
}

export function useAppearanceMode(): [AppearanceMode, () => void] {
  const [mode, setMode] = useState<AppearanceMode>(() => getAppearanceMode())
  useEffect(() => {
    const onChange = (m: AppearanceMode) => setMode(m)
    listeners.add(onChange)
    return () => {
      listeners.delete(onChange)
    }
  }, [])
  const toggle = useCallback(() => {
    toggleAppearanceMode()
  }, [])
  return [mode, toggle]
}
