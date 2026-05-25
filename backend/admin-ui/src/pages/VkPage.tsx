import { useState, useEffect } from 'react'
import { Key, RefreshCw, CheckCircle, XCircle, AlertTriangle, Eye, EyeOff, Check } from 'lucide-react'

export default function VkPage({ token }: { token: string }) {
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [hashes, setHashes] = useState<any[]>([])
  const [saving, setSaving] = useState(false)
  const [recreating, setRecreating] = useState(false)
  const [saveStatus, setSaveStatus] = useState<'idle' | 'success' | 'error'>('idle')
  const [saveMsg, setSaveMsg] = useState('')
  const [hashMsg, setHashMsg] = useState('')

  const fetchHashes = async () => {
    try {
      const res = await fetch('/api/admin/vk/hashes', {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (res.ok) setHashes(await res.json())
    } catch {}
  }

  const fetchCredentials = async () => {
    try {
      const res = await fetch('/api/admin/vk/credentials', {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (res.ok) {
        const data = await res.json()
        if (data.login) setLogin(data.login)
      }
    } catch {}
  }

  useEffect(() => {
    fetchHashes()
    fetchCredentials()
  }, [])

  const saveCredentials = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!login.trim() || !password.trim()) return
    setSaving(true)
    setSaveStatus('idle')
    setSaveMsg('')
    try {
      const res = await fetch('/api/admin/vk/credentials', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ login, password }),
      })
      const data = await res.json()
      if (res.ok) {
        setSaveStatus('success')
        setSaveMsg(data.message || 'Credentials сохранены успешно')
        setPassword('')
        setTimeout(() => setSaveStatus('idle'), 4000)
      } else {
        setSaveStatus('error')
        setSaveMsg(data.detail || 'Ошибка сохранения')
      }
    } catch {
      setSaveStatus('error')
      setSaveMsg('Ошибка соединения с сервером')
    }
    setSaving(false)
  }

  const recreateHashes = async () => {
    setRecreating(true)
    setHashMsg('')
    try {
      const res = await fetch('/api/admin/vk/recreate', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      })
      const data = await res.json()
      setHashMsg(data.message || 'Запрос отправлен')
      setTimeout(fetchHashes, 3000)
    } catch {
      setHashMsg('Ошибка запроса')
    }
    setRecreating(false)
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <h1 className="text-xl font-bold">VK Аккаунт и тоннели</h1>

      {/* Credentials form */}
      <div className="bg-[#111] border border-[#222] rounded-xl p-6">
        <h2 className="font-semibold mb-1 flex items-center gap-2">
          <Key className="w-4 h-4" /> VK Credentials
        </h2>
        <p className="text-[#555] text-xs mb-4">
          AI-ассистент использует этот аккаунт для создания звонков и получения TURN-хешей.
        </p>

        <form onSubmit={saveCredentials} className="space-y-3">
          <input
            type="text"
            value={login}
            onChange={e => setLogin(e.target.value)}
            placeholder="Логин ВКонтакте (телефон или email)"
            className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-4 py-2.5 text-sm text-white focus:outline-none focus:border-[#444] transition-colors"
          />

          <div className="relative">
            <input
              type={showPassword ? 'text' : 'password'}
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="Пароль"
              className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-4 py-2.5 pr-11 text-sm text-white focus:outline-none focus:border-[#444] transition-colors"
            />
            <button
              type="button"
              onClick={() => setShowPassword(v => !v)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-[#555] hover:text-white transition-colors p-1"
              tabIndex={-1}
            >
              {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>

          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={saving}
              className={`flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold transition-all disabled:opacity-50 ${
                saveStatus === 'success'
                  ? 'bg-green-500 text-white'
                  : saveStatus === 'error'
                  ? 'bg-red-500/20 border border-red-500/50 text-red-400'
                  : 'bg-white text-black hover:bg-[#e0e0e0]'
              }`}
            >
              {saving ? (
                <>
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                  Сохраняем...
                </>
              ) : saveStatus === 'success' ? (
                <>
                  <Check className="w-3.5 h-3.5" />
                  Сохранено!
                </>
              ) : (
                'Сохранить'
              )}
            </button>

            {saveMsg && saveStatus !== 'idle' && (
              <span className={`text-xs ${saveStatus === 'success' ? 'text-green-400' : 'text-red-400'}`}>
                {saveMsg}
              </span>
            )}
          </div>
        </form>
      </div>

      {/* Hashes */}
      <div className="bg-[#111] border border-[#222] rounded-xl p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">VK Хеши (TURN туннели)</h2>
          <button
            onClick={recreateHashes}
            disabled={recreating}
            className="flex items-center gap-2 bg-[#1a1a1a] border border-[#2a2a2a] px-4 py-2 rounded-lg text-xs hover:border-white transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${recreating ? 'animate-spin' : ''}`} />
            Пересоздать все
          </button>
        </div>

        {hashMsg && (
          <div className="mb-3 bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2 text-xs text-[#aaa]">
            {hashMsg}
          </div>
        )}

        {hashes.length === 0 ? (
          <div className="text-center py-8 text-[#555]">
            <AlertTriangle className="w-8 h-8 mx-auto mb-2 text-yellow-500" />
            <p className="text-sm">Хеши не созданы. Сохраните VK credentials и нажмите «Пересоздать все».</p>
          </div>
        ) : (
          <div className="space-y-2">
            {hashes.map(h => (
              <div key={h.id} className="flex items-center gap-3 bg-[#151515] rounded-lg px-4 py-3">
                {h.is_active
                  ? <CheckCircle className="w-4 h-4 text-green-400 flex-shrink-0" />
                  : <XCircle className="w-4 h-4 text-red-400 flex-shrink-0" />}
                <span className="text-xs text-[#555] w-12">Слот {h.slot}</span>
                <span className="font-mono text-xs flex-1 text-[#ccc] break-all">{h.hash}</span>
                <span className="text-xs text-[#555]">Сбоев: {h.fail_count}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="bg-[#111] border border-yellow-900/50 rounded-xl p-4">
        <p className="text-xs text-yellow-500/80 leading-relaxed">
          <strong>Важно:</strong> При создании звонка ВКонтакте всегда нажимайте
          «Просто завершить», а не «Завершить для всех» — иначе хеш перестанет работать.
          AI-ассистент проверяет хеши каждые 5 минут и пересоздаёт при сбое.
        </p>
      </div>
    </div>
  )
}
