import { useState, useEffect } from 'react'
import api, { isLoggedIn, setServerUrl } from './api'
import LoginScreen from './pages/LoginScreen'
import MainScreen from './pages/MainScreen'
import { AppErrorBoundary } from './components/AppErrorBoundary'
import type { ClientTheme } from './clientTheme'
import { getCachedTheme, saveCachedTheme } from './themeStore'
import { runAppStateMigrationIfNeeded } from './appStateMigration'
import { checkForUpdate, type UpdateInfo } from './updateCheck'

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
  const [resetToken, setResetToken] = useState<string | null>(null)
  const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null)

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
    const api_ = (window as any).electronAPI
    const onReset = ({ token }: { token: string }) => {
      if (token) {
        setResetToken(token)
        setScreen('login')
      }
    }
    api_?.onResetPasswordLink?.(onReset)
    return () => api_?.removeResetPasswordLinkListeners?.()
  }, [])

  const handleLoginDone = (themeData: ClientTheme | null) => {
    if (themeData) {
      setTheme(themeData)
      saveCachedTheme(themeData)
    }
    setResetToken(null)
    setScreen('main')
  }

  const handleLogout = () => {
    setResetToken(null)
    setScreen('login')
    const cached = getCachedTheme()
    if (cached) setTheme(cached)
    void loadThemeFromServer().then(t => {
      if (t) setTheme(t)
    })
  }

  return (
    <AppErrorBoundary>
      <div className="w-full h-full">
        {screen === 'login' && (
          <LoginScreen
            theme={theme}
            resetToken={resetToken}
            onResetDone={() => setResetToken(null)}
            onLogin={handleLoginDone}
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
