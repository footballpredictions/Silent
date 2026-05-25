import { useState, useEffect } from 'react'
import { isLoggedIn, setServerUrl } from './api'
import LoginScreen from './pages/LoginScreen'
import MainScreen from './pages/MainScreen'

const SERVER_URL = 'https://132-243-234-162.nip.io'

type Screen = 'login' | 'main'

export default function App() {
  const [screen, setScreen] = useState<Screen>('login')
  const [theme, setTheme] = useState<any>(null)

  useEffect(() => {
    setServerUrl(SERVER_URL)
    if (isLoggedIn()) {
      setScreen('main')
    } else {
      setScreen('login')
    }
  }, [])

  const handleLoginDone = (themeData: any) => {
    setTheme(themeData)
    setScreen('main')
  }
  const handleLogout = () => setScreen('login')

  return (
    <div className="w-full h-full bg-white">
      {screen === 'login' && <LoginScreen onLogin={handleLoginDone} />}
      {screen === 'main' && <MainScreen theme={theme} onLogout={handleLogout} />}
    </div>
  )
}
