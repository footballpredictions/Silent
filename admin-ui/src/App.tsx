import { useState, useEffect, useCallback } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import UsersPage from './pages/UsersPage'
import SubscriptionsPage from './pages/SubscriptionsPage'
import VkPage from './pages/VkPage'
import PromoPage from './pages/PromoPage'
import ThemePage from './pages/ThemePage'
import UpdatesPage from './pages/UpdatesPage'
import Layout from './components/Layout'
import { ErrorBoundary } from './components/ErrorBoundary'

async function validateAdminToken(token: string): Promise<boolean> {
  try {
    const res = await fetch('/api/admin/stats', {
      headers: { Authorization: `Bearer ${token}` },
    })
    return res.ok
  } catch {
    return false
  }
}

function App() {
  const [token, setToken] = useState<string | null>(null)
  const [booting, setBooting] = useState(true)

  useEffect(() => {
    const stored = localStorage.getItem('admin_token')
    if (!stored) {
      setBooting(false)
      return
    }
    validateAdminToken(stored).then(ok => {
      if (ok) setToken(stored)
      else localStorage.removeItem('admin_token')
    }).finally(() => setBooting(false))
  }, [])

  const handleLogin = (t: string) => {
    localStorage.setItem('admin_token', t)
    setToken(t)
  }

  const handleLogout = useCallback(() => {
    localStorage.removeItem('admin_token')
    setToken(null)
  }, [])

  if (booting) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center">
        <p className="text-[#888] text-sm">Загрузка...</p>
      </div>
    )
  }

  return (
    <ErrorBoundary>
      <BrowserRouter>
        {!token ? (
          <LoginPage onLogin={handleLogin} />
        ) : (
          <Layout onLogout={handleLogout}>
            <Routes>
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="/dashboard" element={<DashboardPage token={token} onUnauthorized={handleLogout} />} />
              <Route path="/users" element={<UsersPage token={token} />} />
              <Route path="/subscriptions" element={<SubscriptionsPage token={token} />} />
              <Route path="/vk" element={<VkPage token={token} />} />
              <Route path="/promo" element={<PromoPage token={token} />} />
              <Route path="/theme" element={<ThemePage token={token} />} />
              <Route path="/updates" element={<UpdatesPage token={token} />} />
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Routes>
          </Layout>
        )}
      </BrowserRouter>
    </ErrorBoundary>
  )
}

export default App
