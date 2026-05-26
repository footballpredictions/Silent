import { useState, useEffect } from 'react'
import api, {
  saveTokens,
  startNewSession,
  saveSessionDeviceId,
  clearSessionFingerprint,
  clearTokens,
} from '../api'
import {
  cacheVpnConfig,
  getVkUserId,
  saveVkUserId,
  getBootstrapHash,
  saveBootstrapHash,
  isVkReady,
} from '../vkConfig'
import VkLoginSection from '../components/VkLoginSection'

export default function LoginScreen({ onLogin }: { onLogin: (theme: any) => void }) {
  const [tab, setTab] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [regDone, setRegDone] = useState(false)
  const [vkMsg, setVkMsg] = useState('')
  const [vkLinking, setVkLinking] = useState(false)
  const [vkUserId, setVkUserId] = useState<number | null>(() => {
    const id = getVkUserId()
    return id > 0 ? id : null
  })
  const [bootstrapHash, setBootstrapHash] = useState<string | null>(getBootstrapHash)
  const vkReady = isVkReady()

  useEffect(() => {
    const id = getVkUserId()
    if (id > 0) setVkUserId(id)
    setBootstrapHash(getBootstrapHash())
  }, [])

  useEffect(() => {
    const api_ = (window as any).electronAPI
    if (!api_?.onVkDeepLink) return
    const handler = ({ boot, vk }: { boot?: string; vk?: number | null }) => {
      if (vk != null && vk > 0) {
        saveVkUserId(vk)
        setVkUserId(vk)
      }
      if (boot) {
        saveBootstrapHash(boot)
        setBootstrapHash(boot)
      }
      refreshVkState()
      setVkMsg('VK готов. Первый хеш получен — войдите в аккаунт.')
      setVkLinking(false)
    }
    api_.onVkDeepLink(handler)
    return () => api_.removeVkDeepLinkListeners?.()
  }, [])

  const refreshVkState = () => {
    const id = getVkUserId()
    setVkUserId(id > 0 ? id : null)
    setBootstrapHash(getBootstrapHash())
  }

  const handleLinkVk = async () => {
    setVkLinking(true)
    setVkMsg('Открытие VK...')
    try {
      const res = await api.post('/api/auth/vk/guest/link/start')
      const { auth_url, state } = res.data
      ;(window as any).electronAPI?.openExternal(auth_url)
      for (let i = 0; i < 90; i++) {
        await new Promise(r => setTimeout(r, 2000))
        const st = await api.get('/api/auth/vk/guest/status', { params: { state } })
        if (st.data.completed) {
          if (st.data.vk_user_id) {
            saveVkUserId(st.data.vk_user_id)
            setVkUserId(st.data.vk_user_id)
          }
          if (st.data.bootstrap_hash) {
            saveBootstrapHash(st.data.bootstrap_hash)
            setBootstrapHash(st.data.bootstrap_hash)
          }
          refreshVkState()
          setVkMsg('VK готов. Первый хеш получен — войдите в аккаунт.')
          return
        }
      }
      setVkMsg('Завершите вход VK в браузере или вернитесь в приложение.')
    } catch (e: any) {
      setVkMsg(e.response?.data?.detail || 'Не удалось начать привязку VK')
    } finally {
      setVkLinking(false)
    }
  }

  const openLoginSession = async (): Promise<boolean> => {
    const fp = startNewSession()
    try {
      const reg = await api.post('/api/vpn/device/register', {
        device_name: 'PC',
        device_type: 'pc',
        device_fingerprint: fp,
      })
      saveSessionDeviceId(reg.data.device_id)
      cacheVpnConfig(reg.data)
      return true
    } catch (e: any) {
      clearSessionFingerprint()
      clearTokens()
      setError(e.response?.data?.detail || 'Достигнут лимит устройств (3). Выйдите на другом устройстве.')
      return false
    }
  }

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true); setError('')
    try {
      const res = await api.post('/api/auth/login', { email, password })
      saveTokens(res.data.access_token, res.data.refresh_token)

      const localVkId = getVkUserId()
      if (localVkId > 0) {
        try {
          const att = await api.post('/api/auth/vk/link/attach', { vk_user_id: localVkId })
          if (att.data.bootstrap_hash) {
            saveBootstrapHash(att.data.bootstrap_hash)
            setBootstrapHash(att.data.bootstrap_hash)
          }
          refreshVkState()
        } catch (err: any) {
          setVkMsg(err.response?.data?.detail || 'Не удалось привязать VK к аккаунту')
        }
      }

      if (!(await openLoginSession())) return
      const themeRes = await api.get('/api/vpn/theme').catch(() => ({ data: null }))
      onLogin(themeRes.data)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Ошибка входа')
    } finally { setLoading(false) }
  }

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true); setError('')
    try {
      await api.post('/api/auth/register', { email, password })
      setRegDone(true)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Ошибка регистрации')
    } finally { setLoading(false) }
  }

  const inputCls = "w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-black transition-colors"

  return (
    <div className="flex flex-col h-full">
      <div className="h-8 bg-black flex items-center px-4 flex-shrink-0" style={{ WebkitAppRegion: 'drag' } as any}>
        <span className="text-xs text-gray-500 tracking-widest">SILENT VPN</span>
        <div className="ml-auto flex gap-2" style={{ WebkitAppRegion: 'no-drag' } as any}>
          <button onClick={() => (window as any).electronAPI?.minimize()} className="w-3 h-3 rounded-full bg-gray-600 hover:bg-gray-400 transition-colors" />
          <button onClick={() => (window as any).electronAPI?.close()} className="w-3 h-3 rounded-full bg-gray-600 hover:bg-red-400 transition-colors" />
        </div>
      </div>

      <div className="flex-1 flex flex-col px-5 pt-6 pb-5 overflow-y-auto">
        <div className="text-center mb-5">
          <div className="w-14 h-14 bg-black rounded-2xl flex items-center justify-center mx-auto mb-3">
            <span className="text-white font-bold text-xl">S</span>
          </div>
          <h1 className="font-bold text-base tracking-widest">SILENT</h1>
        </div>

        <VkLoginSection
          vkReady={vkReady}
          vkUserId={vkUserId}
          bootstrapHash={bootstrapHash}
          vkMsg={vkMsg}
          linking={vkLinking}
          onLinkVk={handleLinkVk}
        />

        <div className="flex bg-gray-100 rounded-xl p-1 mb-4">
          {(['login', 'register'] as const).map(t => (
            <button key={t} onClick={() => { setTab(t); setError(''); setRegDone(false) }}
              className={`flex-1 py-1.5 rounded-lg text-xs font-medium transition-colors ${tab === t ? 'bg-black text-white' : 'text-gray-500'}`}>
              {t === 'login' ? 'Войти' : 'Регистрация'}
            </button>
          ))}
        </div>

        {regDone ? (
          <div className="flex-1 flex flex-col items-center justify-center text-center gap-3">
            <div className="w-12 h-12 bg-gray-100 rounded-full flex items-center justify-center">
              <span className="text-2xl">✉️</span>
            </div>
            <p className="text-sm font-medium">Подтвердите email</p>
            <p className="text-xs text-gray-500">Ссылка отправлена на {email}</p>
            <button onClick={() => { setTab('login'); setRegDone(false) }}
              className="mt-2 text-xs text-black underline">Войти</button>
          </div>
        ) : (
          <form onSubmit={tab === 'login' ? handleLogin : handleRegister} className="space-y-3">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Email</label>
              <input type="email" value={email} onChange={e => setEmail(e.target.value)} required
                placeholder="you@example.com" className={inputCls} style={{ userSelect: 'text' } as any} />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Пароль</label>
              <input type="password" value={password} onChange={e => setPassword(e.target.value)} required
                placeholder="••••••••" className={inputCls} style={{ userSelect: 'text' } as any} />
            </div>
            {error && <p className="text-red-500 text-xs">{error}</p>}
            <button type="submit" disabled={loading}
              className="w-full bg-black text-white rounded-xl py-3 text-sm font-semibold hover:bg-gray-800 disabled:opacity-50 transition-colors">
              {loading ? '...' : tab === 'login' ? 'Войти' : 'Зарегистрироваться'}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
