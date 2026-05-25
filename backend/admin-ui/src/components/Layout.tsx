import { NavLink } from 'react-router-dom'
import { LayoutDashboard, Users, Hash, Tag, Palette, LogOut, Shield, ScrollText } from 'lucide-react'

const nav = [
  { to: '/dashboard', icon: LayoutDashboard, label: 'Дашборд' },
  { to: '/users', icon: Users, label: 'Пользователи' },
  { to: '/vk', icon: Hash, label: 'VK / Тоннели' },
  { to: '/promo', icon: Tag, label: 'Промокоды' },
  { to: '/theme', icon: Palette, label: 'Оформление' },
  { to: '/logs', icon: ScrollText, label: 'Логи' },
]

export default function Layout({ children, onLogout }: { children: React.ReactNode; onLogout: () => void }) {
  return (
    <div className="flex h-screen bg-[#0a0a0a] text-white">
      {/* Sidebar */}
      <aside className="w-56 bg-[#111] border-r border-[#222] flex flex-col">
        <div className="p-6 border-b border-[#222]">
          <div className="flex items-center gap-2">
            <Shield className="w-6 h-6 text-white" />
            <span className="font-bold text-lg tracking-widest">SILENT</span>
          </div>
          <p className="text-xs text-[#555] mt-1">Admin Panel</p>
        </div>

        <nav className="flex-1 p-3 space-y-1">
          {nav.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                  isActive
                    ? 'bg-white text-black font-medium'
                    : 'text-[#888] hover:text-white hover:bg-[#1a1a1a]'
                }`
              }
            >
              <Icon className="w-4 h-4" />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="p-3 border-t border-[#222]">
          <button
            onClick={onLogout}
            className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-[#888] hover:text-white hover:bg-[#1a1a1a] w-full transition-colors"
          >
            <LogOut className="w-4 h-4" />
            Выйти
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        <div className="p-8">
          {children}
        </div>
      </main>
    </div>
  )
}
