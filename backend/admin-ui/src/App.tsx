import { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import UsersPage from './pages/UsersPage'
import VkPage from './pages/VkPage'
import PromoPage from './pages/PromoPage'
import ThemePage from './pages/ThemePage'
import LogsPage from './pages/LogsPage'
import Layout from './components/Layout'

function App() {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('admin_token'))

  const handleLogin = (t: string) => {
    localStorage.setItem('admin_token', t)
    setToken(t)
  }

  const handleLogout = () => {
    localStorage.removeItem('admin_token')
    setToken(null)
  }

  if (!token) {
    return <LoginPage onLogin={handleLogin} />
  }

  return (
    <BrowserRouter>
      <Layout onLogout={handleLogout}>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<DashboardPage token={token} />} />
          <Route path="/users" element={<UsersPage token={token} />} />
          <Route path="/vk" element={<VkPage token={token} />} />
          <Route path="/promo" element={<PromoPage token={token} />} />
          <Route path="/theme" element={<ThemePage token={token} />} />
          <Route path="/logs" element={<LogsPage token={token} />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}

export default App
