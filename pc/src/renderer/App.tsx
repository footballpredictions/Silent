import { useState, useEffect } from 'react'
import { isLoggedIn, clearTokens, clearSessionFingerprint, initServerUrl } from './api'
import LoginScreen from './pages/LoginScreen'
import MainScreen from './pages/MainScreen'
import ServerSetupScreen from './pages/ServerSetupScreen'

type Screen = 'setup' | 'login' | 'main'

export default function App() {
  const [screen, setScreen] = useState<Screen>('setup')
  const [theme, setTheme] = useState<any>(null)

  useEffect(() => {
    initServerUrl()
    if (!isLoggedIn()) {
      if (localStorage.getItem('silent_token')) {
        clearTokens()
        clearSessionFingerprint()
      }
      setScreen('login')
    } else {
      setScreen('main')
    }
  }, [])

  const handleSetupDone = () => setScreen('login')
  const handleLoginDone = (themeData: any) => {
    setTheme(themeData)
    setScreen('main')
  }
  const handleLogout = () => setScreen('login')

  return (
    <div className="w-full h-full bg-white">
      {screen === 'setup' && <ServerSetupScreen onDone={handleSetupDone} />}
      {screen === 'login' && <LoginScreen onLogin={handleLoginDone} />}
      {screen === 'main' && <MainScreen theme={theme} onLogout={handleLogout} />}
    </div>
  )
}
