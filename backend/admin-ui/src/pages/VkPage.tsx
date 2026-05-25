import { useState, useEffect } from 'react'
import { Key, RefreshCw, CheckCircle, XCircle, AlertTriangle } from 'lucide-react'

export default function VkPage({ token }: { token: string }) {
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [hashes, setHashes] = useState<any[]>([])
  const [saving, setSaving] = useState(false)
  const [recreating, setRecreating] = useState(false)
  const [msg, setMsg] = useState('')

  const fetchHashes = async () => {
    const res = await fetch('/api/admin/vk/hashes', {
      headers: { Authorization: `Bearer ${token}` },
    })
    setHashes(await res.json())
  }

  useEffect(() => { fetchHashes() }, [])

  const saveCredentials = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setMsg('')
    try {
      const res = await fetch('/api/admin/vk/credentials', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ login, password }),
      })
      const data = await res.json()
      setMsg(data.message || 'Сохранено')
      setLogin(''); setPassword('')
    } catch { setMsg('Ошибка сохранения') }
    setSaving(false)
  }

  const recreateHashes = async () => {
    setRecreating(true)
    setMsg('')
    try {
      const res = await fetch('/api/admin/vk/recreate', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      })
      const data = await res.json()
      setMsg(data.message)
      setTimeout(fetchHashes, 2000)
    } catch { setMsg('Ошибка') }
    setRecreating(false)
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <h1 className="text-xl font-bold">VK Аккаунт и тоннели</h1>

      <div className="bg-[#111] border border-[#222] rounded-xl p-6">
        <h2 className="font-semibold mb-1 flex items-center gap-2"><Key className="w-4 h-4" /> VK Credentials</h2>
        <p className="text-[#555] text-xs mb-4">AI-ассистент использует этот аккаунт для создания звонков и получения TURN-хешей.</p>
        <form onSubmit={saveCredentials} className="space-y-3">
          <input
            type="text" value={login} onChange={e => setLogin(e.target.value)}
            placeholder="Логин ВКонтакте (телефон или email)"
            className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-4 py-2.5 text-sm text-white focus:outline-none focus:border-[#444]"
          />
          <input
            type="password" value={password} onChange={e => setPassword(e.target.value)}
            placeholder="Пароль"
            className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-4 py-2.5 text-sm text-white focus:outline-none focus:border-[#444]"
          />
          <button type="submit" disabled={saving}
            className="bg-white text-black px-5 py-2.5 rounded-lg text-sm font-semibold hover:bg-[#e0e0e0] disabled:opacity-50 transition-colors">
            {saving ? 'Сохраняем...' : 'Сохранить'}
          </button>
        </form>
      </div>

      <div className="bg-[#111] border border-[#222] rounded-xl p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">VK Хеши (TURN туннели)</h2>
          <button onClick={recreateHashes} disabled={recreating}
            className="flex items-center gap-2 bg-[#1a1a1a] border border-[#2a2a2a] px-4 py-2 rounded-lg text-xs hover:border-white transition-colors disabled:opacity-50">
            <RefreshCw className={`w-3.5 h-3.5 ${recreating ? 'animate-spin' : ''}`} />
            Пересоздать все
          </button>
        </div>

        {hashes.length === 0 ? (
          <div className="text-center py-8 text-[#555]">
            <AlertTriangle className="w-8 h-8 mx-auto mb-2 text-yellow-500" />
            <p className="text-sm">Хеши не созданы. Сохраните VK credentials и нажмите "Пересоздать все".</p>
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

      {msg && (
        <div className="bg-[#111] border border-[#222] rounded-xl px-4 py-3 text-sm text-[#aaa]">
          {msg}
        </div>
      )}

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
