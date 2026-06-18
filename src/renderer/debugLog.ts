/** Буфер логов для UI «Лог» — как Android DebugLog.kt */

import { pushAppLog } from './vpnLogStore'

export type LogLevel = 'D' | 'I' | 'W' | 'E' | 'T'

export interface DebugLogItem {
  ts: number
  tag: string
  level: LogLevel
  message: string
  repeat?: number
}

const KEY = 'silent_debug_logs'
const MAX_ITEMS = 600
const UI_FLUSH_MS = 1500
const isDev = import.meta.env.DEV

let listeners: Array<(items: DebugLogItem[]) => void> = []
let pendingFlush: ReturnType<typeof setTimeout> | null = null
let dirty = false

function read(): DebugLogItem[] {
  try {
    const raw = localStorage.getItem(KEY)
    const arr = raw ? (JSON.parse(raw) as DebugLogItem[]) : []
    return Array.isArray(arr) ? arr : []
  } catch {
    return []
  }
}

function notify() {
  const snapshot = readLogs()
  listeners.forEach(l => l(snapshot))
}

function scheduleFlush() {
  dirty = true
  if (pendingFlush) return
  pendingFlush = setTimeout(() => {
    pendingFlush = null
    if (!dirty) return
    dirty = false
    notify()
  }, UI_FLUSH_MS)
}

function flushNow() {
  if (pendingFlush) {
    clearTimeout(pendingFlush)
    pendingFlush = null
  }
  dirty = false
  notify()
}

function dedupeKey(tag: string, message: string): string {
  const m = message.replace(/\d+/g, '#').slice(0, 120)
  return `${tag}|${m}`
}

function append(level: LogLevel, tag: string, message: string, flushUi: boolean) {
  const msg = String(message ?? '')
  const items = read()
  const key = dedupeKey(tag, msg)
  const last = items[items.length - 1]
  if (last && dedupeKey(last.tag, last.message) === key && last.level === level) {
    last.repeat = (last.repeat || 1) + 1
    last.ts = Date.now()
  } else {
    items.push({ ts: Date.now(), tag, level, message: msg, repeat: 1 })
  }
  while (items.length > MAX_ITEMS) items.shift()
  localStorage.setItem(KEY, JSON.stringify(items))
  if (flushUi) flushNow()
  else scheduleFlush()
}

export function readLogs(): DebugLogItem[] {
  return read().slice().sort((a, b) => a.ts - b.ts)
}

export function clearLogs() {
  localStorage.removeItem(KEY)
  flushNow()
}

export function subscribeLogs(cb: (items: DebugLogItem[]) => void): () => void {
  listeners.push(cb)
  cb(readLogs())
  return () => {
    listeners = listeners.filter(l => l !== cb)
  }
}

/** Verbose — только dev (libclient flood). */
export function logD(tag: string, message: string) {
  if (isDev) append('D', tag, message, false)
}

export function logI(tag: string, message: string) {
  append('I', tag, message, true)
}

export function logW(tag: string, message: string) {
  append('W', tag, message, true)
}

export function logE(tag: string, message: string) {
  append('E', tag, message, true)
}

/** Только UI «Лог», без console. */
export function traceUi(tag: string, message: string) {
  append('T', tag, message, true)
}

export function pushLog(tag: string, message: string, level: 'I' | 'W' | 'E' = 'I') {
  pushAppLog(tag, message, level)
}

export function ingestMainLog(payload: { tag?: string; level?: string; message?: string }) {
  const tag = payload.tag || 'Main'
  const msg = payload.message || ''
  const lvl = (payload.level || 'I').toUpperCase()
  const level = lvl === 'E' ? 'E' : lvl === 'W' ? 'W' : 'I'
  pushAppLog(tag, msg, level)
}

export function formatLogLine(item: DebugLogItem): string {
  const d = new Date(item.ts)
  const t = d.toLocaleTimeString('ru-RU', { hour12: false })
  const ms = String(d.getMilliseconds()).padStart(3, '0')
  const rep = item.repeat && item.repeat > 1 ? ` (×${item.repeat})` : ''
  return `${t}.${ms} ${item.level}/${item.tag}: ${item.message}${rep}`
}
