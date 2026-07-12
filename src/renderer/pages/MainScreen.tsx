import { useState, useEffect, useCallback, useRef } from 'react'
import { Menu, X, ChevronRight, Pencil } from 'lucide-react'
import api, {
  clearTokens,
  getDeviceFingerprint,
  getSessionDeviceId,
  saveSessionDeviceId,
  clearSessionFingerprint,
  clearSessionDeviceId,
  getServerUrl,
  getPublicApiBaseUrl,
} from '../api'
import {
  cacheVpnConfig, getCachedVpnConfig, clearCachedVpnConfig,
  getVkUserId, saveVkUserId,
  type VpnConfigPayload,
} from '../vkConfig'
import {
  disconnectBootstrapVpn,
  isBootstrapVpnActive,
  resetBootstrapRendererState,
} from '../bootstrapVpn'
import { fetchVpnConfigWithKeys } from '../vpnConfigFetch'
import { waitVpnReady } from '../vpnReady'
import { warmupBrowsingPath } from '../warmupBrowsingPath'
import SupportTelegramLinks from '../components/SupportTelegramLinks'
import VpnToggle from '../components/VpnToggle'
import DebugLogPanel, { DebugLogButton } from '../components/DebugLogPanel'
import ThemeModeToggle from '../components/ThemeModeToggle'
import WindowControls from '../components/WindowControls'
import { AppErrorBoundary } from '../components/AppErrorBoundary'
import { needsNeonGlow, neonTextShadow, resolveThemePalette } from '../clientTheme'
import { useAppearanceMode } from '../appearanceStore'
import { menuDrawerStyle } from '../uiTokens'
import AppExclusionsPanel from '../components/AppExclusionsPanel'
import MenuHashesPanel from '../components/MenuHashesPanel'
import MenuDnsPanel from '../components/MenuDnsPanel'
import { getDnsPreset } from '../dnsPreset'
import MenuVkCredModePanel from '../components/MenuVkCredModePanel'
import { prepareVpnConnectConfig } from '../prepareVpnConnect'
import { attachVkCredLaunchParams } from '../vkCredStore'
import { isDebugBuild } from '../debugBuild'
import { telegramProxyDeepLink } from '../telegramProxyLink'
import { notifyDisconnect } from '../vpnBackendSync'
import { pushLog, logI } from '../debugLog'
import { clearVpnLogs } from '../vpnLogStore'
import { SessionTrace } from '../sessionTrace'
import { setMainVpnSessionActive } from '../tunnelApi'
import {
  getCachedProfile,
  saveCachedProfile,
  clearCachedProfile,
} from '../profileStore'
import { checkForUpdate, getAppVersion, type UpdateInfo } from '../updateCheck'
import { getApiBaseUrl } from '../tunnelApi'
import { notifyConnect } from '../vpnBackendSync'
import { flushPendingHashFailures, resetHashFailureReporter } from '../hashFailureReporter'
import {
  startConfigSync,
  stopConfigSync,
  resetConfigSyncOnLogout,
  seedConfigSyncRevision,
} from '../configSync'

const isDevBuild = isDebugBuild

interface DeviceInfo {
  id: string
  device_name: string
  device_type: string
  device_fingerprint?: string | null
  is_connected: boolean
  last_connected?: string | null
}

/** id в профиле и device_id из register могут отличаться форматом — сверяем также по fingerprint. */
function isCurrentSessionDevice(d: DeviceInfo, sessionId: string | null): boolean {
  if (!sessionId) return false
  const sid = String(sessionId)
  const did = String(d.id)
  if (did === sid) return true
  if (sid.length >= 8 && did.length >= 8 && (did.startsWith(sid) || sid.startsWith(did))) return true
  try {
    const fp = getDeviceFingerprint()
    if (fp && d.device_fingerprint && fp === d.device_fingerprint) return true
  } catch { /* ignore */ }
  return false
}

function deviceOnlineLabel(
  d: DeviceInfo,
  sessionId: string | null,
  localOnline: boolean,
  connecting: boolean,
): string {
  const isSelf = isCurrentSessionDevice(d, sessionId)
  if (d.is_connected) return 'В сети'
  if (isSelf && connecting) return 'Подключение…'
  if (isSelf && localOnline) return 'В сети'
  if (d.last_connected) {
    try {
      const dt = new Date(d.last_connected)
      if (!Number.isNaN(dt.getTime())) {
        return `Был в сети ${dt.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}`
      }
    } catch { /* ignore */ }
  }
  return 'Не в сети'
}

interface Profile {
  email: string; display_id: string
  is_admin?: boolean
  vk_linked?: boolean; vk_user_id?: number | null
  subscription: { is_active: boolean; plan_type: string | null; expires_at: string | null; days_left: number }
  devices: DeviceInfo[]
  devices_count: number
  max_devices: number
}

type MenuPage = null | 'devices' | 'subscription' | 'exceptions' | 'vk_cred' | 'hashes' | 'dns' | 'bonuses' | 'support' | 'about'

const PLAN_LABELS: Record<string, string> = {
  trial: 'Пробный период',
  test: 'Тестовый режим',
  monthly: 'Месяц',
  quarterly: '3 месяца',
  yearly: 'Год',
  unlimited: 'Бессрочно',
}

function planLabel(planType: string | null | undefined): string {
  if (!planType) return '—'
  return PLAN_LABELS[planType] || planType
}

function deviceLimitLabel(profile: Profile | null | undefined): string {
  if (!profile) return '3'
  if (profile.is_admin || profile.max_devices <= 0) return '∞'
  return String(profile.max_devices)
}

function sessionsBadge(profile: Profile | null | undefined): string {
  const count = profile?.devices_count || 0
  return `${count}/${deviceLimitLabel(profile)}`
}

function isUnlimitedLikePlan(profile: Profile | null | undefined): boolean {
  const plan = profile?.subscription?.plan_type
  return !!profile?.is_admin || plan === 'unlimited' || plan === 'test'
}

function deviceTypeLabel(type: string): string {
  const t = (type || '').toLowerCase()
  if (t === 'android') return 'Android'
  if (t === 'pc' || t === 'windows') return 'ПК'
  if (t === 'ios') return 'iOS'
  return type ? type.charAt(0).toUpperCase() + type.slice(1) : '—'
}

function defaultDeviceName(type: string): string {
  const t = (type || '').toLowerCase()
  if (t === 'android') return 'Android'
  if (t === 'pc' || t === 'windows') return 'PC'
  if (t === 'ios') return 'iOS'
  return deviceTypeLabel(type)
}

function sessionCustomLabel(d: DeviceInfo): string | null {
  const defaults = new Set(['Android', 'ПК', 'PC', 'iOS', 'Windows'])
  if (defaults.has(d.device_name) || d.device_name.startsWith('Bootstrap-')) return null
  return d.device_name
}

export default function MainScreen({
  theme: initialTheme,
  initialUpdateInfo = null,
  onLogout,
}: {
  theme: any
  initialUpdateInfo?: UpdateInfo | null
  onLogout: () => void
}) {
  const [connected, setConnected] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [disconnecting, setDisconnecting] = useState(false)
  const [appearanceMode, toggleAppearance] = useAppearanceMode()
  const [profile, setProfile] = useState<Profile | null>(() => getCachedProfile<Profile>())
  const [clientTheme, setClientTheme] = useState<any>(initialTheme)
  const sessionDeviceId = getSessionDeviceId()
  const [menuOpen, setMenuOpen] = useState(false)
  const [menuPage, setMenuPage] = useState<MenuPage>(null)
  const [promoCode, setPromoCode] = useState('')
  const [promoMsg, setPromoMsg] = useState('')
  const [referralInfo, setReferralInfo] = useState<{
    referral_code: string
    referral_link: string
    invited_count: number
    rewarded_count: number
    pending_count: number
    bonus_days: number
  } | null>(null)
  const [referralCopyMsg, setReferralCopyMsg] = useState('')
  const [showDebugLog, setShowDebugLog] = useState(false)
  const [renameTarget, setRenameTarget] = useState<DeviceInfo | null>(null)
  const [renameText, setRenameText] = useState('')
  const [renameSaving, setRenameSaving] = useState(false)
  const [deleteSavingId, setDeleteSavingId] = useState<string | null>(null)
  const [activeWorkers, setActiveWorkers] = useState(0)
  const connectLockRef = useRef(false)
  const connectGenRef = useRef(0)
  const onlineMarkedRef = useRef(false)
  const subscriptionExpiredHandledRef = useRef(false)
  const pendingConnectAfterSubscriptionRefreshRef = useRef(false)
  const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(initialUpdateInfo)
  const [updateDownloading, setUpdateDownloading] = useState(false)
  const [updateProgress, setUpdateProgress] = useState(0)
  const [hashSyncKey, setHashSyncKey] = useState(0)

  const applyServerProfile = useCallback((p: Profile) => {
    // Сессия пропала на сервере — не разлогиниваем: перерегистрируем устройство.
    const sid = getSessionDeviceId()
    if (sid && Array.isArray(p.devices)) {
      const stillHere = p.devices.some(d => isCurrentSessionDevice(d, sid))
      if (!stillHere) {
        pushLog('Main', 'current session missing — re-register, keep login', 'W')
        void (async () => {
          try {
            const fp = getDeviceFingerprint()
            const config = await fetchVpnConfigWithKeys(fp)
            if (config?.device_id) {
              saveSessionDeviceId(String(config.device_id))
              cacheVpnConfig(config)
              pushLog('Main', `session recovered device=${String(config.device_id).slice(0, 8)}…`)
            }
          } catch (e) {
            pushLog('Main', `session recover fail: ${(e as Error)?.message || e}`, 'W')
          }
        })()
      }
    }

    setProfile(p)
    saveCachedProfile(p)
    if (isBootstrapVpnActive()) return
    const vpnActive = connected || connecting || disconnecting
    const hasAccess = p.is_admin || p.subscription?.is_active
    if (hasAccess) {
      subscriptionExpiredHandledRef.current = false
      return
    }
    if (vpnActive && !hasAccess) {
      if (subscriptionExpiredHandledRef.current) return
      subscriptionExpiredHandledRef.current = true
      pushLog('Main', 'subscription expired on server — disconnect VPN', 'W')
      void (async () => {
        setDisconnecting(true)
        let fp: string | null = null
        try {
          try { fp = getDeviceFingerprint() } catch { /* ignore */ }
          setMainVpnSessionActive(false)
          if (fp) await notifyDisconnect(fp)
          if ((window as any).electronAPI?.vpnDisconnect) {
            await (window as any).electronAPI.vpnDisconnect()
          }
        } catch (e) {
          pushLog('Main', `forced disconnect: ${(e as Error)?.message || e}`, 'W')
        } finally {
          onlineMarkedRef.current = false
          setConnected(false)
          setConnecting(false)
          setDisconnecting(false)
          connectLockRef.current = false
        }
        // Не используем alert: он блокирует UI и может зациклиться при частом profile sync.
        pushLog('Main', 'Пробный период закончился. Откройте меню → Подписка', 'W')
        setMenuOpen(true)
        setMenuPage('subscription')
      })()
    }
  }, [connected, connecting, disconnecting])

  const fetchProfile = useCallback(async () => {
    try {
      const res = await api.get('/api/users/me')
      applyServerProfile(res.data as Profile)
      if (res.data.vk_user_id) saveVkUserId(res.data.vk_user_id)
      return res.data as Profile
    } catch {
      const cached = getCachedProfile<Profile>()
      if (cached) setProfile(cached)
      return cached
    }
  }, [applyServerProfile])

  useEffect(() => {
    // На главном экране bootstrap-состояние не должно жить.
    resetBootstrapRendererState()
    const api_ = (window as any).electronAPI
    void (async () => {
      try {
        const st = await api_?.vpnIsReady?.()
        // Если после логина остался bootstrap-туннель — гасим его.
        if (st?.bootstrap && !st?.ready) {
          await disconnectBootstrapVpn()
          pushLog('Main', 'stale bootstrap VPN stopped on main screen')
        }
      } catch {
        /* ignore */
      }
    })()
  }, [])

  useEffect(() => {
    void seedConfigSyncRevision()
    fetchProfile()
    const subMsg = localStorage.getItem('silent_subscription_msg')
    if (subMsg) {
      localStorage.removeItem('silent_subscription_msg')
      setMenuOpen(true)
      setMenuPage('subscription')
    }
  }, [fetchProfile])

  useEffect(() => {
    if (menuPage !== 'devices') return
    fetchProfile()
    const id = window.setInterval(() => fetchProfile(), 30_000)
    return () => clearInterval(id)
  }, [menuPage, fetchProfile])

  const loadReferral = useCallback(async () => {
    try {
      const r = await api.get('/api/users/me/referral')
      if (r.data?.referral_link) {
        setReferralInfo(r.data)
        setReferralCopyMsg('')
        return
      }
      setReferralInfo(null)
      setReferralCopyMsg('Не удалось загрузить ссылку')
    } catch (e: any) {
      setReferralInfo(null)
      const detail = e?.response?.data?.detail
      setReferralCopyMsg(typeof detail === 'string' ? detail : 'Не удалось загрузить ссылку')
    }
  }, [])

  useEffect(() => {
    if (menuPage !== 'bonuses') return
    void loadReferral()
  }, [menuPage, loadReferral])

  useEffect(() => {
    setMainVpnSessionActive(connected)
    startConfigSync({
      onTheme: t => setClientTheme(t),
      onProfile: p => applyServerProfile(p as Profile),
      onHashesUpdated: () => setHashSyncKey(k => k + 1),
      isVpnConnected: () => connected,
      isPollAllowed: () => !connecting && !disconnecting,
    })
    return () => stopConfigSync()
  }, [connected, connecting, disconnecting, applyServerProfile])

  useEffect(() => {
    api.get('/api/vpn/theme').then(r => setClientTheme(r.data)).catch(() => {})
  }, [connected])

  const applyTunnelApiFromCache = useCallback(() => {
    setMainVpnSessionActive(true)
  }, [])

  useEffect(() => {
    if (connected) return
    const cfg = getCachedVpnConfig()
    if (cfg?.wg_private_key?.trim() && cfg?.server_public_key?.trim()) return
    let fp: string | null = null
    try {
      fp = getDeviceFingerprint()
    } catch {
      return
    }
    void fetchVpnConfigWithKeys(fp).then(c => {
      if (c) cacheVpnConfig(c)
    })
  }, [connected])

  const markOnlineOnServer = useCallback(async () => {
    if (onlineMarkedRef.current) return
    onlineMarkedRef.current = true
    applyTunnelApiFromCache()
    try {
      const ok = await notifyConnect(true)
      if (!ok) {
        onlineMarkedRef.current = false
        return
      }
      await seedConfigSyncRevision()
      void flushPendingHashFailures()
    } catch {
      onlineMarkedRef.current = false
    }
  }, [applyTunnelApiFromCache])

  useEffect(() => {
    const api_ = (window as any).electronAPI
    api_?.vpnIsReady?.().then((r: { ready?: boolean; workers?: number }) => {
      if (r?.ready) {
        setConnected(true)
        setConnecting(false)
        if (r.workers) setActiveWorkers(r.workers)
        void markOnlineOnServer()
        pushLog('Main', `VPN уже активен (${r.workers ?? '?'} воркеров)`)
      }
    }).catch(() => {})
  }, [markOnlineOnServer, applyTunnelApiFromCache])

  useEffect(() => {
    const api_ = (window as any).electronAPI
    if (!api_?.onVpnStopped) return
    let mounted = true
    const onStopped = () => {
      if (connecting && !connected) {
        // Во время старта возможен краткий restart транспорта; не сбрасываем UI раньше времени.
        return
      }
      onlineMarkedRef.current = false
      setMainVpnSessionActive(false)
      resetHashFailureReporter()
      setConnected(false)
      setConnecting(false)
      setActiveWorkers(0)
      void checkForUpdate().then(info => {
        if (info?.available) setUpdateInfo(info)
      })
    }
    const onError = (msg: string) => {
      pushLog('VPN', msg, 'E')
      setConnecting(false)
      setConnected(false)
    }
    const onReady = (payload: boolean | { ok?: boolean; bootstrap?: boolean }) => {
      const ok = typeof payload === 'object' ? !!payload?.ok : !!payload
      const bootstrap = typeof payload === 'object' ? !!payload?.bootstrap : false
      if (!ok || bootstrap) return
      if (ok) {
        setConnected(true)
        setConnecting(false)
        void markOnlineOnServer()
      }
    }
    const onLog = (line: string) => {
      if (!mounted || !line?.trim()) return
      const m = line.match(/Активных:\s*(\d+)/)
      if (m) setActiveWorkers(parseInt(m[1], 10))
      const reg = line.match(/зарегистрирован \(всего:\s*(\d+)\)/)
      if (reg) setActiveWorkers(parseInt(reg[1], 10))
    }
    api_.onVpnStopped(onStopped)
    api_.onVpnError?.(onError)
    api_.onVpnReady?.(onReady)
    api_.onVpnLog?.(onLog)
    return () => { mounted = false }
  }, [markOnlineOnServer, applyTunnelApiFromCache, connecting, connected])

  useEffect(() => {
    if (initialUpdateInfo?.available) setUpdateInfo(initialUpdateInfo)
  }, [initialUpdateInfo])

  useEffect(() => {
    let cancelled = false
    const run = async () => {
      // Раньше пропускали при connected — OTA не приходило, пока VPN включён.
      // При VPN check/download идут через tunnel 10.66.66.1 (main.js).
      if (connecting) return
      const info = await checkForUpdate()
      if (!cancelled && info?.available) setUpdateInfo(info)
    }
    void run()
    const id = window.setInterval(() => void run(), 5 * 60_000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [connected, connecting])

  // Сразу после выхода в full VPN — одна проверка через tunnel (как Android).
  useEffect(() => {
    if (!connected) return
    let cancelled = false
    void checkForUpdate().then(info => {
      if (!cancelled && info?.available) setUpdateInfo(info)
    })
    return () => { cancelled = true }
  }, [connected])

  useEffect(() => {
    const api_ = (window as any).electronAPI
    if (!api_?.onUpdateProgress) return
    api_.onUpdateProgress((pct: number) => setUpdateProgress(pct))
    return () => api_.removeUpdateListeners?.()
  }, [])

  const handleUpdateClick = async () => {
    if (!updateInfo?.download_url || updateDownloading) return
    const api_ = (window as any).electronAPI
    if (!api_?.downloadUpdate) return
    setUpdateDownloading(true)
    setUpdateProgress(0)
    // Relative / GitHub URL → main сам выберет tunnel (/api/updates/download/pc) или прямой GitHub.
    const dlPath = updateInfo.download_url || updateInfo.github_download_url || ''
    try {
      const apiAny = api_ as any
      const res = apiAny.downloadUpdateMeta
        ? await apiAny.downloadUpdateMeta({
            url: dlPath,
            filename: updateInfo.filename || 'update.exe',
            tunnelUrl: updateInfo.tunnel_download_url || '/api/updates/download/pc',
            expectedSize: updateInfo.size || 0,
          })
        : await api_.downloadUpdate(dlPath, updateInfo.filename || 'update.exe')
      if (res?.ok && res.path && api_.installUpdate) {
        setUpdateProgress(100)
        const inst = await api_.installUpdate(res.path)
        if (!inst?.ok) {
          alert(inst?.error || 'Не удалось запустить установщик')
          setUpdateDownloading(false)
        }
        // при успехе приложение закроется — установщик NSIS откроется сам
      } else {
        alert(res?.error || 'Ошибка загрузки обновления')
        setUpdateDownloading(false)
      }
    } catch {
      alert('Ошибка загрузки обновления')
      setUpdateDownloading(false)
    }
  }

  useEffect(() => {
    if (!connecting || connected) return
    const api_ = (window as any).electronAPI
    const tick = async () => {
      try {
        const r = await api_?.vpnIsReady?.()
        if (r?.ready) {
          setConnected(true)
          setConnecting(false)
          void markOnlineOnServer()
        }
      } catch { /* ignore */ }
    }
    void tick()
    const id = window.setInterval(() => void tick(), 500)
    return () => clearInterval(id)
  }, [connecting, connected, markOnlineOnServer])

  const DEVICE_FINGERPRINT = () => getDeviceFingerprint()

  const handleToggle = async () => {
    if (connectLockRef.current || connecting || disconnecting) return

    if (connected) {
      connectGenRef.current += 1
      pendingConnectAfterSubscriptionRefreshRef.current = false
      setConnected(false)
      setDisconnecting(false)
      setConnecting(false)
      pushLog('Main', 'disconnect')
      SessionTrace.enter('Main.connect', 'disconnect')
      const fp = DEVICE_FINGERPRINT()
      setMainVpnSessionActive(false)
      onlineMarkedRef.current = false
      // UI сразу в «выкл»; lock не держим — можно сразу включить снова (stop в фоне + waitWgStopIdle)
      connectLockRef.current = false
      void (async () => {
        try {
          await notifyDisconnect(fp)
        } catch (err: any) {
          if (err.response?.status === 402 || err.response?.status === 403) alert(err.response.data.detail)
        }
        try {
          if ((window as any).electronAPI?.vpnDisconnect) {
            await (window as any).electronAPI.vpnDisconnect()
          }
        } catch { /* ignore */ }
        fetchProfile()
      })()
      return
    }

    connectLockRef.current = true
    // UI сразу: не ждать fetchProfile / prepare (раньше давало ~5–8с «Подключение…»).
    setConnecting(true)
    setConnected(true)
    setMainVpnSessionActive(true)
    if (!connected) {
      setActiveWorkers(0)
      clearVpnLogs()
    }
    pushLog('Main', 'connect start')
    SessionTrace.enter('Main.connect', 'start')
    const connectGen = ++connectGenRef.current
    try {
      const fp = DEVICE_FINGERPRINT()
      if (!connected) {
        const api_ = (window as any).electronAPI
        const already = await api_?.vpnIsReady?.().catch(() => null)
        if (connectGen !== connectGenRef.current) return
        if (already?.ready) {
          setConnecting(false)
          connectLockRef.current = false
          pushLog('Main', 'VPN уже поднят, UI синхронизирован')
          return
        }
        // Профиль в фоне не блокирует тумблер; доступ проверим по кешу + свежий fetch без await в критическом пути.
        const cachedProfile = getCachedProfile<Profile>()
        const cachedHasAccess = !cachedProfile || cachedProfile.is_admin || cachedProfile.subscription?.is_active
        if (!cachedHasAccess) {
          setConnected(false)
          setConnecting(false)
          setMainVpnSessionActive(false)
          connectLockRef.current = false
          pendingConnectAfterSubscriptionRefreshRef.current = true
          alert('Пробный период закончился. Оформите подписку в меню → Подписка.')
          setMenuOpen(true)
          setMenuPage('subscription')
          return
        }
        void fetchProfile().then(p => {
          if (connectGen !== connectGenRef.current) return
          const hasAccess = !p || p.is_admin || p.subscription?.is_active
          if (!hasAccess) {
            pendingConnectAfterSubscriptionRefreshRef.current = true
            void (window as any).electronAPI?.vpnDisconnect?.()
            setConnected(false)
            setMainVpnSessionActive(false)
            alert('Пробный период закончился. Оформите подписку в меню → Подписка.')
            setMenuOpen(true)
            setMenuPage('subscription')
          }
        }).catch(() => { /* ignore */ })

        let config: VpnConfigPayload | null = getCachedVpnConfig()
        if (config?.device_id) saveSessionDeviceId(String(config.device_id))
        if (!config?.wg_private_key?.trim() || !config?.server_public_key?.trim() || !config?.vk_hashes?.length) {
          config = null
        }
        if (!config) {
          try {
            config = await fetchVpnConfigWithKeys(fp)
          } catch (e: any) {
            if (connectGen !== connectGenRef.current) return
            if (e.response?.status === 402) {
              pendingConnectAfterSubscriptionRefreshRef.current = true
              setConnected(false)
              setMainVpnSessionActive(false)
              alert(e.response?.data?.detail || 'Оформите подписку для доступа к интернету.')
              setMenuOpen(true)
              setMenuPage('subscription')
              fetchProfile()
              return
            }
            throw e
          }
          if (connectGen !== connectGenRef.current) return
          if (config) {
            cacheVpnConfig(config)
            if (config.device_id) saveSessionDeviceId(String(config.device_id))
            pushLog(
              'Main',
              `device/register OK device=${String(config.device_id || '').slice(0, 8)} hashes=${config.vk_hashes?.length ?? 0}`,
            )
          }
        } else {
          pushLog(
            'Main',
            `connect from cache device=${String(config.device_id || '').slice(0, 8)} hashes=${config.vk_hashes?.length ?? 0}`,
          )
        }
        if (!config) {
          pushLog('Main', 'no VPN config', 'E')
          setConnected(false)
          setMainVpnSessionActive(false)
          alert('Сервер недоступен. Выйдите и настройте hash на экране входа.')
          return
        }
        if (!config.wg_private_key?.trim() || !config.server_public_key?.trim()) {
          pushLog('Main', 'missing WG keys', 'E')
          setConnected(false)
          setMainVpnSessionActive(false)
          alert('Нет ключей WireGuard. Перезайдите в аккаунт или проверьте сервер.')
          return
        }

        setConnecting(false)
        connectLockRef.current = false

        if (isBootstrapVpnActive()) {
          // Не блокируем UI — bootstrap гасим в фоне, затем connect.
          void (async () => {
            await disconnectBootstrapVpn()
            if (connectGen !== connectGenRef.current) return
            pushLog('Main', 'bootstrap VPN stopped before connect')
            await runMainVpnConnect(config!, fp, connectGen)
          })()
        } else {
          void runMainVpnConnect(config, fp, connectGen)
        }
      }
    } catch (err: any) {
      if (connectGen !== connectGenRef.current) return
      if (err.response?.status === 402 || err.response?.status === 403) {
        pendingConnectAfterSubscriptionRefreshRef.current = true
      }
      if (err.response?.status === 402 || err.response?.status === 403) alert(err.response.data.detail)
      setConnected(false)
      setMainVpnSessionActive(false)
    } finally {
      if (connectGen === connectGenRef.current) {
        connectLockRef.current = false
        setConnecting(false)
      }
    }
  }

  const runMainVpnConnect = async (
    config: VpnConfigPayload,
    fp: string,
    connectGen: number,
  ) => {
    try {
      if (!(window as any).electronAPI?.vpnConnect) return
      pushLog('Main', 'vpnConnect start')
      // prepare не блокирует тумблер (уже ON); хеши из кеша — быстро.
      const connectCfg = attachVkCredLaunchParams(await prepareVpnConnectConfig(config, fp))
      if (connectGen !== connectGenRef.current) return
      pushLog('Main', `vpnConnect n=${connectCfg.stream_count} hashes=${connectCfg.vk_hashes?.length ?? 0} vk=${connectCfg.vkAuthMode}`)
      const res = await (window as any).electronAPI.vpnConnect(connectCfg)
      if (connectGen !== connectGenRef.current) return
      if (res?.error) {
        pushLog('Main', `vpnConnect: ${res.error}`, 'E')
        setConnected(false)
        setMainVpnSessionActive(false)
        alert(res.error)
        return
      }
      pendingConnectAfterSubscriptionRefreshRef.current = false
      const ready = await waitVpnReady(undefined, connectCfg.stream_count ?? 63)
      if (connectGen !== connectGenRef.current) return
      if (!ready) {
        pushLog('Main', 'connect timeout', 'E')
        setConnected(false)
        setMainVpnSessionActive(false)
        alert('WireGuard не поднялся. Установите Silent VPN 1.0.51+ или проверьте службу WireGuardTunnel$wg-turn')
        await (window as any).electronAPI?.vpnDisconnect?.()
        await api.post('/api/vpn/disconnect', { device_fingerprint: fp }).catch(() => null)
        await fetchProfile()
        return
      }
      await markOnlineOnServer()
      void warmupBrowsingPath().catch(() => null)
      // Повторный прогрев когда воркеры догонят — превью TG иначе «ещё не загрузилось».
      window.setTimeout(() => { void warmupBrowsingPath(8000).catch(() => null) }, 5000)
      fetchProfile()
    } catch (err: any) {
      if (connectGen !== connectGenRef.current) return
      pushLog('Main', `vpnConnect failed: ${err?.message || err}`, 'E')
      setConnected(false)
      setMainVpnSessionActive(false)
    }
  }

  useEffect(() => {
    if (!pendingConnectAfterSubscriptionRefreshRef.current) return
    const hasAccess = !!(profile && (profile.is_admin || profile.subscription?.is_active))
    if (!hasAccess) return
    if (connected || connecting || disconnecting || connectLockRef.current) return
    pendingConnectAfterSubscriptionRefreshRef.current = false
    pushLog('Main', 'subscription restored — auto reconnect')
    void handleToggle()
  }, [profile, connected, connecting, disconnecting])

  const logoutBusyRef = useRef(false)
  const [loggingOut, setLoggingOut] = useState(false)

  const handleLogout = () => {
    if (logoutBusyRef.current) return
    logoutBusyRef.current = true
    setLoggingOut(true)
    setMenuOpen(false)
    setMenuPage(null)

    const fp = (() => { try { return DEVICE_FINGERPRINT() } catch { return null } })()
    const token = localStorage.getItem('silent_token')
    const needVpnStop = connected || connecting || disconnecting

    // Сразу UI. Stable fingerprint переживает logout → следующий вход reuse слот (как Android).
    setMainVpnSessionActive(false)
    setConnected(false)
    setConnecting(false)
    setDisconnecting(false)
    connectLockRef.current = false
    onlineMarkedRef.current = false
    clearCachedVpnConfig()
    clearCachedProfile()
    clearSessionDeviceId()
    clearSessionFingerprint()
    clearTokens()
    resetConfigSyncOnLogout()
    onLogout()

    void (async () => {
      try {
        if (fp && token) {
          await Promise.race([
            api.post(
              '/api/users/logout',
              { device_fingerprint: fp },
              {
                headers: { Authorization: `Bearer ${token}` },
                timeout: 3_000,
              } as any,
            ),
            new Promise<void>(r => setTimeout(r, 3_000)),
          ])
        }
      } catch { /* ignore */ }
      try {
        if (needVpnStop) {
          void (window as any).electronAPI?.vpnDisconnect?.({ fast: true })
        }
      } catch { /* ignore */ }
      logoutBusyRef.current = false
    })()
  }

  const saveRename = async () => {
    if (!renameTarget || renameSaving) return
    setRenameSaving(true)
    try {
      const name = renameText.trim() || defaultDeviceName(renameTarget.device_type)
      await api.patch(`/api/users/devices/${renameTarget.id}`, { device_name: name })
      setRenameTarget(null)
      fetchProfile()
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Ошибка переименования')
    } finally {
      setRenameSaving(false)
    }
  }

  const deleteSession = async (d: DeviceInfo) => {
    if (deleteSavingId) return
    const isSelf = isCurrentSessionDevice(d, sessionDeviceId)
    const msg = isSelf
      ? 'Удалить эту сессию и выйти из аккаунта?'
      : 'Удалить сессию этого устройства?'
    if (!window.confirm(msg)) return
    setDeleteSavingId(d.id)
    try {
      await api.delete(`/api/users/devices/${d.id}`)
      if (isSelf) {
        handleLogout()
      } else {
        await fetchProfile()
      }
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Не удалось удалить сессию')
    } finally {
      setDeleteSavingId(null)
    }
  }

  const palette = resolveThemePalette(clientTheme, appearanceMode)
  const bg = palette.bg
  const fg = palette.fg
  const toggleOn = palette.toggleOn
  const toggleOff = palette.toggleOff
  const fontFamily = palette.fontFamily
  const appTitle = palette.appTitle
  const muted = palette.muted
  const border = palette.border
  const updateBarBg = palette.updateBarBg
  const updateBarFg = palette.updateBarFg
  const updateBarProgress = palette.updateBarProgress
  const updateLabelAvailable = clientTheme?.update_bar_label_available || 'Доступно обновление'
  const updateLabelDownloading = clientTheme?.update_bar_label_downloading || 'Скачивание…'
  const GREEN = palette.green
  const TEST_PURPLE = palette.purple

  const statusLabel = disconnecting
    ? 'Отключение…'
    : connecting
    ? 'Подключение…'
    : connected
      ? 'Подключено'
      : 'Отключено'
  const statusColor = connecting || disconnecting ? muted : connected ? GREEN : muted
  const statusGlow = needsNeonGlow(statusColor, palette.dark) ? neonTextShadow(statusColor) : undefined
  const localOnline = connected || connecting || disconnecting

  return (
    <div className="relative flex flex-col h-full overflow-hidden" style={{ background: bg, color: fg, fontFamily }}>
      <div
        className="h-9 flex-shrink-0 relative flex items-center border-b px-1.5"
        style={{ WebkitAppRegion: 'drag', background: bg, borderColor: border } as React.CSSProperties}
      >
        {/* Равные боковые слоты → заголовок визуально по центру окна */}
        <div
          className="w-[76px] shrink-0 flex items-center justify-start"
          style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
        >
          <button
            onClick={() => { setMenuOpen(true); setMenuPage(null) }}
            style={{ color: fg }}
            className="p-1 hover:opacity-60 transition-opacity"
          >
            <Menu className="w-4 h-4" />
          </button>
        </div>
        <span
          className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-xs font-bold tracking-widest truncate max-w-[100px] pointer-events-none text-center"
          style={{ color: fg }}
        >
          {appTitle}
        </span>
        <div
          className="ml-auto w-[76px] shrink-0 flex items-center justify-end gap-0"
          style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
        >
          <ThemeModeToggle mode={appearanceMode} onToggle={toggleAppearance} color={fg} />
          <DebugLogButton onClick={() => setShowDebugLog(true)} />
          <WindowControls />
        </div>
      </div>

      <div className="flex-1 flex flex-col items-center justify-center pb-16 gap-6 px-4">
        <div className="text-center">
          <div
            className="text-xs font-medium tracking-widest uppercase"
            style={{ color: statusColor, letterSpacing: '0.15em', textShadow: statusGlow }}
          >
            {statusLabel}
          </div>
        </div>

        <VpnToggle
          connected={connected}
          connecting={connecting}
          disconnecting={disconnecting}
          toggleOn={toggleOn}
          toggleOff={toggleOff}
          fg={fg}
          bg={bg}
          onToggle={() => void handleToggle()}
        />
      </div>

      <div className="absolute bottom-0 left-0 right-0 p-4 border-t" style={{ background: bg, borderColor: border }}>
        {updateInfo?.available ? (
          <button
            onClick={() => void handleUpdateClick()}
            disabled={updateDownloading}
            className="w-full rounded-xl py-2 text-xs font-semibold transition-colors disabled:opacity-70 relative overflow-hidden"
            style={{ background: updateBarBg, color: updateBarFg }}>
            {updateDownloading && (
              <span
                className="absolute inset-y-0 left-0"
                style={{
                  width: `${updateProgress}%`,
                  background: updateBarProgress,
                  opacity: 0.35,
                }}
              />
            )}
            <span className="relative">
              {updateDownloading
                ? `${updateLabelDownloading} ${updateProgress}%`
                : `${updateLabelAvailable} v${updateInfo.version}`}
            </span>
          </button>
        ) : profile?.subscription?.plan_type === 'test' ? (
          <div className="text-center">
            <div className="text-xs font-semibold" style={{ color: TEST_PURPLE }}>Тестовый режим</div>
            <div className="text-xs mt-0.5" style={{ color: muted }}>Безлимит</div>
          </div>
        ) : profile?.is_admin || profile?.subscription?.plan_type === 'unlimited' ? (
          <div className="text-center">
            <div className="text-xs font-semibold" style={{ color: GREEN }}>Бессрочно</div>
            <div className="text-xs mt-0.5" style={{ color: muted }}>Полный доступ</div>
          </div>
        ) : profile?.subscription?.is_active && profile?.subscription?.plan_type === 'trial' ? (
          <div className="text-center">
            <div className="text-xs font-semibold" style={{ color: '#2563EB' }}>Пробный период</div>
            <div className="text-xs mt-0.5" style={{ color: muted }}>
              осталось {profile?.subscription?.days_left ?? 0} дн.
            </div>
          </div>
        ) : profile?.subscription?.is_active ? (
          <div className="text-center">
            <div className="text-xs font-semibold" style={{ color: GREEN }}>Оплачено</div>
            <div className="text-xs mt-0.5" style={{ color: muted }}>
              до {profile?.subscription?.expires_at
                ? profile.subscription.expires_at.split('T')[0].split('-').reverse().join('.')
                : '—'}
            </div>
          </div>
        ) : profile ? (
          <button onClick={() => { setMenuOpen(true); setMenuPage('subscription') }}
            className="w-full rounded-xl py-2 text-xs font-semibold transition-colors"
            style={{ background: fg, color: bg }}>
            Оформить подписку
          </button>
        ) : null}
      </div>

      {renameTarget && (
        <div className="absolute inset-0 z-[60] flex items-center justify-center bg-black/30 p-4">
          <div className="w-full max-w-xs rounded-xl p-4 shadow-xl" style={{ background: bg }}>
            <div className="text-sm font-semibold mb-3">Приписать имя</div>
            <input
              value={renameText}
              onChange={e => setRenameText(e.target.value.slice(0, 64))}
              placeholder="Например: Рабочий ПК"
              className="theme-field w-full rounded-xl px-3 py-2 text-sm mb-3 focus:outline-none"
              style={{
                userSelect: 'text',
                background: palette.fieldBg,
                color: palette.fieldText,
                border: `1px solid ${palette.borderStrong}`,
                ['--field-ph' as any]: palette.fieldPlaceholder,
              } as any}
              autoFocus
            />
            <div className="flex gap-2">
              <button
                onClick={() => setRenameTarget(null)}
                disabled={renameSaving}
                className="flex-1 py-2 text-xs rounded-xl"
                style={{ border: `1px solid ${palette.borderStrong}`, color: fg, background: 'transparent' }}
              >
                Отмена
              </button>
              <button
                onClick={saveRename}
                disabled={renameSaving}
                className="flex-1 py-2 text-xs rounded-xl disabled:opacity-50"
                style={{ background: fg, color: bg }}
              >
                Сохранить
              </button>
            </div>
          </div>
        </div>
      )}

      {menuOpen && menuPage === null && (
        <div className="absolute inset-0 z-50 flex">
          <div
            className="h-full flex flex-col"
            style={{ ...menuDrawerStyle, background: bg, borderRight: `1px solid ${palette.borderStrong}` }}
          >
            <div
              className="p-4 flex items-center justify-between"
              style={{ borderBottom: `1px solid ${palette.border}` }}
            >
              <div>
                <div className="text-xs font-semibold truncate max-w-[140px]">{profile?.email || '—'}</div>
                <div className="text-xs text-gray-400 mt-0.5">Аккаунт: {profile?.display_id || '—'}</div>
                {sessionDeviceId && (
                  <div className="text-xs text-gray-400 mt-0.5">
                    Сессия: {sessionDeviceId.slice(0, 8).toUpperCase()}
                  </div>
                )}
              </div>
              <button
                onClick={() => { setMenuOpen(false); setMenuPage(null) }}
                className="p-1 hover:opacity-60"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <nav className="flex-1 p-2 overflow-y-auto">
              {[
                { key: 'subscription', label: 'Подписка' },
                { key: 'exceptions', label: 'Исключения приложений' },
                ...(isDevBuild ? [{ key: 'dns', label: `DNS · ${getDnsPreset().title}` }] : []),
                ...(isDevBuild ? [{ key: 'vk_cred', label: 'Режим VK-кредов' }] : []),
                ...(isDevBuild ? [{ key: 'hashes', label: 'Хеши' }] : []),
                { key: 'bonuses', label: clientTheme?.menu_bonuses_label || 'Бонусы' },
                { key: 'devices', label: `Сессии (${sessionsBadge(profile)})` },
                { key: 'support', label: 'Поддержка' },
                { key: 'about', label: 'О сервисе' },
              ].map(({ key, label }) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => {
                    setMenuPage(key as MenuPage)
                    if (key === 'bonuses') void loadReferral()
                  }}
                  className="w-full flex items-center gap-2 px-3 py-2.5 rounded-lg text-sm text-left transition-colors"
                  style={{ color: fg }}
                >
                  <span className="flex-1 text-left leading-snug">{label}</span>
                  <ChevronRight className="w-3.5 h-3.5 shrink-0" style={{ color: muted }} />
                </button>
              ))}
              {isDevBuild && !!(clientTheme?.telegram_proxy_url || '').trim() && (
                <button
                  type="button"
                  onClick={() => {
                    const url = telegramProxyDeepLink(String(clientTheme.telegram_proxy_url))
                    void (window as any).electronAPI?.openExternal?.(url)
                    setMenuOpen(false)
                    setMenuPage(null)
                  }}
                  className="w-full flex items-center gap-2 px-3 py-2.5 rounded-lg text-sm text-left transition-colors"
                  style={{ color: fg }}
                >
                  <span className="flex-1 text-left leading-snug">
                    {clientTheme?.telegram_proxy_menu_label || 'Ускорить Telegram'}
                  </span>
                  <ChevronRight className="w-3.5 h-3.5 shrink-0" style={{ color: muted }} />
                </button>
              )}
              {profile?.is_admin && (
                <button
                  type="button"
                  onClick={() => { void (window as typeof window & { electronAPI?: { openAdminPanel?: () => Promise<string> } }).electronAPI?.openAdminPanel?.() }}
                  className="w-full flex flex-col items-start gap-0.5 px-3 py-2.5 rounded-lg text-sm text-left transition-colors"
                  style={{ color: fg }}
                >
                  <span className="flex w-full items-center gap-2">
                    <span className="flex-1 leading-snug">Админ-панель</span>
                    <ChevronRight className="w-3.5 h-3.5 shrink-0" style={{ color: muted }} />
                  </span>
                  {connected && (
                    <span className="text-[10px] leading-tight" style={{ color: muted }}>
                      Админка: 132-243-234-162.nip.io
                    </span>
                  )}
                </button>
              )}
              <button
                type="button"
                onClick={handleLogout}
                disabled={loggingOut}
                className="w-full text-left px-3 py-2.5 rounded-lg text-sm text-red-500 hover:bg-red-50 transition-colors mt-2 disabled:opacity-50"
              >
                {loggingOut ? 'Выход…' : 'Выйти'}
              </button>
            </nav>
          </div>
          <div className="flex-1 bg-black/20" onClick={() => { setMenuOpen(false); setMenuPage(null) }} />
        </div>
      )}

      {menuOpen && menuPage !== null && (
        <div
          className="absolute inset-0 z-50 flex flex-col h-full w-full overflow-hidden"
          style={{ background: bg }}
        >
          {menuPage === 'subscription' && (
            <div className="flex-1 p-4 overflow-y-auto w-full">
              <button
                type="button"
                onClick={() => setMenuPage(null)}
                className="text-xs text-gray-400 mb-4 flex items-center gap-1"
              >
                ← Назад
              </button>
              {profile?.subscription?.is_active ? (
                <div className="space-y-2">
                  <div className="text-sm font-semibold">Подписка активна</div>
                  <div className="text-xs text-gray-500">
                    Тариф: {planLabel(profile.subscription?.plan_type)}<br />
                    {isUnlimitedLikePlan(profile)
                      ? 'Безлимитный доступ'
                      : `Осталось: ${profile.subscription?.days_left ?? 0} дней`}
                  </div>
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="text-sm font-semibold">Выберите тариф</div>
                  {[
                    { id: 'monthly', label: 'Месяц', price: '199 ₽' },
                    { id: 'quarterly', label: '3 месяца', price: '499 ₽' },
                    { id: 'yearly', label: 'Год', price: '1 499 ₽' },
                  ].map(plan => (
                    <button key={plan.id}
                      onClick={async () => {
                        try {
                          const res = await api.post('/api/payments/init', { plan_type: plan.id })
                          ;(window as any).electronAPI?.openExternal(res.data.url)
                        } catch (e: any) {
                          alert(e.response?.data?.detail || 'Ошибка')
                        }
                      }}
                      className="w-full flex items-center justify-between bg-black text-white rounded-xl px-3 py-2.5 text-xs font-semibold hover:bg-gray-800 transition-colors">
                      <span>{plan.label}</span>
                      <span>{plan.price}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {menuPage === 'exceptions' && (
            <div className="flex-1 flex flex-col min-h-0 w-full h-full items-stretch text-left">
              <AppExclusionsPanel
                fg={fg}
                muted={muted}
                bg={bg}
                fieldBg={palette.fieldBg}
                fieldText={palette.fieldText}
                fieldPlaceholder={palette.fieldPlaceholder}
                border={border}
                borderStrong={palette.borderStrong}
                dark={palette.dark}
                onBack={() => setMenuPage(null)}
              />
            </div>
          )}

          {menuPage === 'vk_cred' && isDevBuild && (
            <MenuVkCredModePanel
              fg={fg}
              muted={muted}
              vpnRunning={connected || connecting}
              onBack={() => setMenuPage(null)}
            />
          )}
          {menuPage === 'hashes' && isDevBuild && (
            <AppErrorBoundary key={`hashes-${hashSyncKey}`} onReset={() => setMenuPage(null)}>
              <MenuHashesPanel
                key={hashSyncKey}
                fg={fg}
                muted={muted}
                vpnConnected={connected}
                activeWorkers={activeWorkers}
                onBack={() => setMenuPage(null)}
              />
            </AppErrorBoundary>
          )}
          {menuPage === 'dns' && isDevBuild && (
            <MenuDnsPanel
              fg={fg}
              muted={muted}
              vpnConnected={connected}
              onBack={() => setMenuPage(null)}
            />
          )}

          {menuPage === 'bonuses' && (
            <div className="flex-1 p-4 w-full overflow-y-auto">
              <button onClick={() => setMenuPage(null)} className="text-xs mb-4" style={{ color: muted }}>← Назад</button>
              <div className="text-sm font-semibold mb-2" style={{ color: fg }}>
                {clientTheme?.bonuses_title || clientTheme?.menu_bonuses_label || 'Бонусы'}
              </div>
              <p className="text-[11px] mb-4 leading-relaxed whitespace-pre-line" style={{ color: muted }}>
                {clientTheme?.bonuses_intro_text
                  || clientTheme?.bonuses_rules_text
                  || 'Рефералка: отправьте другу ссылку или код. Он регистрируется по ним и оплачивает любую подписку — оба получаете +30 дней. Один бонус на одного друга, до 10 наград за 30 дней.\n\nПромокод: отдельная скидка или доп. дни к тарифу — вводится при регистрации или проверяется здесь.\n\nУсловия программы могут измениться.'}
              </p>

              <div className="text-sm font-semibold mb-1" style={{ color: fg }}>
                {clientTheme?.bonuses_referral_title || 'Ваша ссылка'}
              </div>
              <p className="text-[11px] mb-2 leading-relaxed" style={{ color: muted }}>
                {clientTheme?.bonuses_referral_hint || 'Скопируйте и отправьте другу'}
              </p>
              <input
                readOnly
                value={referralInfo?.referral_link || ''}
                placeholder={referralInfo ? '' : 'Загрузка…'}
                className="theme-field w-full rounded-xl px-3 py-2 text-xs focus:outline-none mb-2"
                style={{
                  userSelect: 'text',
                  background: palette.fieldBg,
                  color: palette.fieldText,
                  border: `1px solid ${palette.borderStrong}`,
                  ['--field-ph' as any]: palette.fieldPlaceholder,
                } as any}
              />
              <button
                type="button"
                onClick={async () => {
                  const link = referralInfo?.referral_link
                  if (!link) {
                    void loadReferral()
                    return
                  }
                  try {
                    await (window as any).electronAPI?.copyToClipboard?.(link)
                    setReferralCopyMsg('Ссылка скопирована')
                  } catch {
                    setReferralCopyMsg('Не удалось скопировать')
                  }
                }}
                className="w-full rounded-xl py-2 text-xs font-semibold transition-colors mb-2"
                style={{ background: fg, color: bg }}
              >
                {referralInfo?.referral_link
                  ? (clientTheme?.bonuses_copy_link_label || 'Копировать ссылку')
                  : 'Повторить загрузку'}
              </button>
              {referralInfo && (
                <p className="text-[11px] mb-3" style={{ color: muted }}>
                  Приглашено: {referralInfo.invited_count} · Награждено: {referralInfo.rewarded_count}
                  {referralInfo.pending_count ? ` · Ожидают оплату: ${referralInfo.pending_count}` : ''}
                </p>
              )}
              {referralCopyMsg && <p className="text-xs mb-3 text-center" style={{ color: muted }}>{referralCopyMsg}</p>}

              <div className="text-sm font-semibold mb-1 mt-4" style={{ color: fg }}>
                {clientTheme?.bonuses_promo_title || 'Промокод'}
              </div>
              <p className="text-[11px] mb-2" style={{ color: muted }}>
                {clientTheme?.bonuses_promo_hint || 'Проверить скидку к тарифу'}
              </p>
              <input value={promoCode} onChange={e => setPromoCode(e.target.value)}
                placeholder="Введите код"
                className="theme-field w-full rounded-xl px-3 py-2 text-sm focus:outline-none"
                style={{
                  userSelect: 'text',
                  background: palette.fieldBg,
                  color: palette.fieldText,
                  border: `1px solid ${palette.borderStrong}`,
                  ['--field-ph' as any]: palette.fieldPlaceholder,
                } as any} />
              <button onClick={async () => {
                try {
                  const res = await api.post('/api/payments/promo/check', { code: promoCode, plan_type: 'monthly' })
                  setPromoMsg(`Скидка ${res.data.discount_percent}%!`)
                } catch (e: any) { setPromoMsg(e.response?.data?.detail || 'Не найден') }
              }} className="mt-2 w-full rounded-xl py-2 text-xs font-semibold transition-colors"
                style={{ background: fg, color: bg }}>
                Проверить
              </button>
              {promoMsg && <p className="text-xs mt-2 text-center" style={{ color: muted }}>{promoMsg}</p>}

              {!!(clientTheme?.bonuses_rules_text || '').trim() && (
                <p className="text-[11px] mt-4 leading-relaxed whitespace-pre-line" style={{ color: muted }}>
                  {clientTheme?.bonuses_rules_text}
                </p>
              )}
            </div>
          )}

          {menuPage === 'devices' && (
            <div className="flex-1 p-4 overflow-y-auto text-left w-full">
              <button type="button" onClick={() => setMenuPage(null)} className="text-xs text-gray-400 mb-4 block text-left">
                ← Назад
              </button>
              <div className="text-sm font-semibold mb-1 text-left">Сессии</div>
              <div className="text-[11px] mb-3 text-left" style={{ color: muted }}>
                VPN онлайн: {profile?.devices?.filter(d => d.is_connected || (localOnline && isCurrentSessionDevice(d, sessionDeviceId))).length || 0} из {profile?.devices_count || 0}
              </div>
              {!profile?.devices?.length && (
                <p className="text-xs text-left" style={{ color: muted }}>Нет зарегистрированных устройств</p>
              )}
              {profile?.devices?.map(d => {
                const isSelf = isCurrentSessionDevice(d, sessionDeviceId)
                const online = d.is_connected || (localOnline && isSelf)
                const statusText = deviceOnlineLabel(d, sessionDeviceId, localOnline, connecting)
                return (
                  <div key={d.id} className="flex items-center gap-2 py-2.5 border-b border-gray-100 text-left">
                    <div className={`w-2.5 h-2.5 rounded-full shrink-0 ${online ? 'bg-green-500' : connecting && isSelf ? 'bg-amber-400' : 'bg-gray-300'}`} />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium truncate" style={{ color: fg }}>
                        {deviceTypeLabel(d.device_type)}
                        {isSelf && (
                          <span className="font-normal text-[11px]" style={{ color: muted }}> · это вы</span>
                        )}
                      </div>
                      <div className="text-[11px] mt-0.5 truncate" style={{ color: online ? GREEN : muted }}>
                        {statusText}
                      </div>
                      {sessionCustomLabel(d) && (
                        <div className="text-[11px] truncate mt-0.5" style={{ color: muted }}>
                          {sessionCustomLabel(d)}
                        </div>
                      )}
                    </div>
                    <button
                      onClick={() => {
                        setRenameTarget(d)
                        setRenameText(sessionCustomLabel(d) || '')
                      }}
                      className="p-1.5 rounded-lg hover:bg-gray-100 shrink-0"
                      title="Подписать"
                    >
                      <Pencil className="w-3.5 h-3.5" style={{ color: muted }} />
                    </button>
                    <button
                      onClick={() => void deleteSession(d)}
                      disabled={deleteSavingId === d.id}
                      className="p-1.5 rounded-lg hover:bg-gray-100 shrink-0 disabled:opacity-40"
                      title="Удалить сессию"
                    >
                      <X className="w-3.5 h-3.5" style={{ color: muted }} />
                    </button>
                  </div>
                )
              })}
            </div>
          )}

          {menuPage === 'support' && (
            <div className="flex-1 p-4 w-full overflow-y-auto">
              <button onClick={() => setMenuPage(null)} className="text-xs text-gray-400 mb-4">← Назад</button>
              <div className="text-sm font-semibold mb-3" style={{ color: fg }}>Поддержка</div>
              <p className="text-xs" style={{ color: muted }}>По вопросам обратитесь через Telegram.</p>
              <SupportTelegramLinks
                channelUrl={clientTheme?.telegram_channel_url}
                supportUrl={clientTheme?.support_url}
                muted={muted}
              />
            </div>
          )}

          {menuPage === 'about' && (
            <div className="flex-1 p-4 w-full overflow-y-auto">
              <button onClick={() => setMenuPage(null)} className="text-xs text-gray-400 mb-4">← Назад</button>
              <div className="text-sm font-semibold mb-1">Silent VPN</div>
              <div className="text-xs text-gray-500 space-y-1">
                <p>Версия {getAppVersion()}</p>
                <p>WireGuard-туннель через VK TURN/DTLS</p>
              </div>
            </div>
          )}
        </div>
      )}
      <DebugLogPanel open={showDebugLog} onClose={() => setShowDebugLog(false)} />
    </div>
  )
}
