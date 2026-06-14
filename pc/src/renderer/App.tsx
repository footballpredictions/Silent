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
  const [screen, setScreen] = useState<Screen>('login')
  const [theme, setTheme] = useState<ClientTheme | null>(() => getCachedTheme())
  const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null)

  useVpnLogSubscription(true)

  useEffect(() => {
    runAppStateMigrationIfNeeded()
    setServerUrl(SERVER_URL)
    void loadThemeFromServer().then(t => {
      if (t) setTheme(t)
    })
    void checkForUpdate().then(info => {
      if (info?.available) setUpdateInfo(info)
    })
    if (isLoggedIn()) {
      setScreen('main')
    } else {
      setScreen('login')
    }
  }, [])

  const handleLoginDone = (themeData: ClientTheme | null) => {
    if (themeData) {
      setTheme(themeData)
      saveCachedTheme(themeData)
    }
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
          <LoginScreen theme={theme} onLogin={handleLoginDone} />
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
