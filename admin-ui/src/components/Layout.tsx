import { useState, useEffect } from 'react'
import { NavLink } from 'react-router-dom'
import { LayoutDashboard, Users, Hash, Gift, Palette, LogOut, Calendar, Menu, X, Download, Hexagon, Network } from 'lucide-react'
import SilentLogo from './SilentLogo'

const nav = [
  { to: '/dashboard', icon: LayoutDashboard, label: 'Дашборд' },
  { to: '/users', icon: Users, label: 'Пользователи' },
  { to: '/subscriptions', icon: Calendar, label: 'Подписки' },
  { to: '/vk', icon: Hash, label: 'VK / Тоннели' },
  { to: '/hive', icon: Hexagon, label: 'Улей' },
  { to: '/proxy', icon: Network, label: 'Прокси' },
  { to: '/bonuses', icon: Gift, label: 'Бонусы' },
  { to: '/theme', icon: Palette, label: 'Оформление' },
  { to: '/updates', icon: Download, label: 'Обновления' },
]

function NavItems({ onClose }: { onClose?: () => void }) {
  return (
    <>
      {nav.map(({ to, icon: Icon, label }) => (
        <NavLink
          key={to}
          to={to}
          onClick={onClose}
          className={({ isActive }) =>
            `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
              isActive
                ? 'bg-white text-black font-medium'
                : 'text-[#888] hover:text-white hover:bg-[#1a1a1a]'
            }`
          }
        >
          <Icon className="w-4 h-4 shrink-0" />
          {label}
        </NavLink>
      ))}
    </>
  )
}

export default function Layout({ children, onLogout }: { children: React.ReactNode; onLogout: () => void }) {
  const [drawerOpen, setDrawerOpen] = useState(false)

  // Close drawer on resize to desktop
  useEffect(() => {
    const handler = () => { if (window.innerWidth >= 768) setDrawerOpen(false) }
    window.addEventListener('resize', handler)
    return () => window.removeEventListener('resize', handler)
  }, [])

  return (
    <div className="flex h-screen bg-[#0a0a0a] text-white overflow-hidden">

      {/* ── Desktop sidebar ── */}
      <aside className="hidden md:flex w-56 shrink-0 bg-[#111] border-r border-[#222] flex-col">
        <div className="p-6 border-b border-[#222]">
          <div className="flex items-center gap-3">
            <SilentLogo size={32} />
            <div>
              <span className="font-bold text-base block leading-tight">Silent VPN</span>
              <p className="text-xs text-[#555]">Админ панель</p>
            </div>
          </div>
        </div>
        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          <NavItems />
        </nav>
        <div className="p-3 border-t border-[#222]">
          <button
            onClick={onLogout}
            className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-[#888] hover:text-white hover:bg-[#1a1a1a] w-full transition-colors"
          >
            <LogOut className="w-4 h-4 shrink-0" />
            Выйти
          </button>
        </div>
      </aside>

      {/* ── Mobile drawer backdrop ── */}
      {drawerOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 md:hidden"
          onClick={() => setDrawerOpen(false)}
        />
      )}

      {/* ── Mobile drawer ── */}
      <aside
        className={`fixed inset-y-0 left-0 z-50 w-64 bg-[#111] border-r border-[#222] flex flex-col transform transition-transform duration-200 md:hidden ${
          drawerOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="p-5 border-b border-[#222] flex items-center justify-between">
          <div className="flex items-center gap-3">
            <SilentLogo size={28} />
            <div>
              <span className="font-bold text-sm block leading-tight">Silent VPN</span>
              <p className="text-xs text-[#555]">Админ панель</p>
            </div>
          </div>
          <button onClick={() => setDrawerOpen(false)} className="text-[#555] hover:text-white p-1">
            <X className="w-5 h-5" />
          </button>
        </div>
        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          <NavItems onClose={() => setDrawerOpen(false)} />
        </nav>
        <div className="p-3 border-t border-[#222]">
          <button
            onClick={() => { setDrawerOpen(false); onLogout() }}
            className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-[#888] hover:text-white hover:bg-[#1a1a1a] w-full transition-colors"
          >
            <LogOut className="w-4 h-4 shrink-0" />
            Выйти
          </button>
        </div>
      </aside>

      {/* ── Main ── */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">

        {/* Mobile top bar */}
        <header className="md:hidden flex items-center gap-3 px-4 py-3 bg-[#111] border-b border-[#222] shrink-0">
          <button
            onClick={() => setDrawerOpen(true)}
            className="text-[#888] hover:text-white p-1 -ml-1"
          >
            <Menu className="w-5 h-5" />
          </button>
          <div className="flex items-center gap-2">
            <SilentLogo size={20} />
            <span className="font-bold text-sm">Silent VPN</span>
          </div>
        </header>

        <main className="flex-1 overflow-auto">
          <div className="p-4 md:p-8">
            {children}
          </div>
        </main>
      </div>
    </div>
  )
}
