import { useState, useEffect } from 'react'
import api, { isLoggedIn, setServerUrl } from './api'
import LoginScreen from './pages/LoginScreen'
import MainScreen from './pages/MainScreen'
import { AppErrorBoundary } from './components/AppErrorBoundary'
import type { ClientTheme } from './clientTheme'

const SERVER_URL = 'https://132-243-234-162.nip.io'

type Screen = 'login' | 'main'

export default function App() {
  const [screen, setScreen] = useState<Screen>('login')
  const [theme, setTheme] = useState<ClientTheme | null>(null)

  useEffect(() => {
    setServerUrl(SERVER_URL)
    api.get('/api/vpn/theme').then(r => setTheme(r.data)).catch(() => setTheme(null))
    if (isLoggedIn()) {
      setScreen('main')
    } else {
      setScreen('login')
    }
  }, [])

  const handleLoginDone = (themeData: ClientTheme | null) => {
    if (themeData) setTheme(themeData)
    setScreen('main')
  }
  const handleLogout = () => setScreen('login')

  return (
    <AppErrorBoundary>
      <div className="w-full h-full">
        {screen === 'login' && <LoginScreen theme={theme} onLogin={handleLoginDone} />}
        {screen === 'main' && <MainScreen theme={theme} onLogout={handleLogout} />}
      </div>
    </AppErrorBoundary>
  )
}
