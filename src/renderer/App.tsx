import { useState, useEffect } from 'react'
import api, { isLoggedIn, setServerUrl } from './api'
import LoginScreen from './pages/LoginScreen'
import MainScreen from './pages/MainScreen'
import { AppErrorBoundary } from './components/AppErrorBoundary'
import type { ClientTheme } from './clientTheme'
import { getCachedTheme, saveCachedTheme } from './themeStore'
import { runAppStateMigrationIfNeeded } from './appStateMigration'
import { checkForUpdate, getAppVersion, type UpdateInfo } from './updateCheck'
import { useVpnLogSubscription } from './useVpnLogSubscription'
import { isDebugBuild } from './debugBuild'

const SERVER_URL = 'https://132-243-234-162.nip.io'

type Screen = 'login' | 'main'

async function loadThemeFromServer(): Promise<ClientTheme | null> {
  try {
    const res = await api.get('/api/vpn/theme')
    if (res.data) {
      saveCachedTheme(res.data)
      return res.data as ClientTheme
    }
  } catch {
    /* offline — cached/default */
  }
  return getCachedTheme()
}

export default function App() {
  const [screen, setScreen] = useState<Screen>(() => (isLoggedIn() ? 'main' : 'login'))
  const [theme, setTheme] = useState<ClientTheme | null>(() => getCachedTheme())
  const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null)
  const [pendingReferralCode, setPendingReferralCode] = useState('')

  useVpnLogSubscription(isDebugBuild)

  useEffect(() => {
    runAppStateMigrationIfNeeded()
    setServerUrl(SERVER_URL)
    void loadThemeFromServer().then(t => {
      if (t) setTheme(t)
    })
    void checkForUpdate().then(info => {
      if (info?.available) setUpdateInfo(info)
    })
    setScreen(isLoggedIn() ? 'main' : 'login')
  }, [])

  useEffect(() => {
    const api_ = (window as any).electronAPI
    if (!api_?.onRefDeepLink) return
    const onRef = (payload: { code?: string }) => {
      const code = String(payload?.code || '').trim()
      if (!code) return
      if (isLoggedIn()) return
      setPendingReferralCode(code)
      setScreen('login')
    }
    api_.onRefDeepLink(onRef)
    return () => {
      api_.removeRefDeepLinkListeners?.()
    }
  }, [])

  const handleLoginDone = (themeData: ClientTheme | null) => {
    if (themeData) {
      setTheme(themeData)
      saveCachedTheme(themeData)
    }
    setPendingReferralCode('')
    setScreen('main')
  }

  const handleLogout = () => {
    setScreen('login')
    const cached = getCachedTheme()
    if (cached) setTheme(cached)
    void loadThemeFromServer().then(t => {
      if (t) setTheme(t)
    })
  }

  return (
    <AppErrorBoundary key={getAppVersion()}>
      <div className="w-full h-full">
        {screen === 'login' && (
          <LoginScreen
            theme={theme}
            onLogin={handleLoginDone}
            initialReferralCode={pendingReferralCode}
          />
        )}
        {screen === 'main' && (
          <MainScreen
            theme={theme}
            initialUpdateInfo={updateInfo}
            onLogout={handleLogout}
          />
        )}
      </div>
    </AppErrorBoundary>
  )
}
