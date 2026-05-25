import { useState, useEffect } from 'react'
import { Link, RefreshCw, CheckCircle, XCircle, AlertTriangle, Plus, Trash2 } from 'lucide-react'

type Status = 'idle' | 'loading' | 'success' | 'error'

function StatusBadge({ status, msg }: { status: Status; msg: string }) {
  if (status === 'idle' || !msg) return null
  const styles: Record<string, string> = {
    loading: 'bg-[#1a1a1a] border-[#333] text-[#aaa]',
    success: 'bg-green-500/10 border-green-500/30 text-green-400',
    error:   'bg-red-500/10  border-red-500/30  text-red-400',
  }
  return (
    <div className={`border rounded-lg px-3 py-2 text-xs leading-relaxed ${styles[status]}`}>
      {msg}
    </div>
  )
}

export default function VkPage({ token }: { token: string }) {
  const [hashes, setHashes] = useState<any[]>([])
  const [newLink, setNewLink]     = useState('')
  const [addStatus, setAddStatus] = useState<Status>('idle')
  const [addMsg, setAddMsg]       = useState('')

  const api = (path: string, opts?: RequestInit) =>
    fetch(path, { headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...opts?.headers }, ...opts })

  const fetchHashes = async () => {
    try {
      const res = await api('/api/admin/vk/hashes')
      if (res.ok) setHashes(await res.json())
    } catch {}
  }

  useEffect(() => { fetchHashes() }, [])

  // Extract hash from VK call link or use raw hash
  const extractHash = (input: string): string => {
    const match = input.match(/call\/join\/([A-Za-z0-9_\-]+)/)
    if (match) return match[1]
    if (/^[A-Za-z0-9_\-]{6,}$/.test(input.trim())) return input.trim()
    return ''
  }

  const addHash = async () => {
    const hash = extractHash(newLink)
    if (!hash) { setAddStatus('error'); setAddMsg('Неверная ссылка. Пример: vk.com/call/join/HASH или просто HASH'); return }
    setAddStatus('loading'); setAddMsg('Добавляем...')
    try {
      const res = await api('/api/admin/vk/hashes/add', {
        method: 'POST', body: JSON.stringify({ hash }),
      })
      const data = await res.json()
      if (data.success) {
        setAddStatus('success'); setAddMsg('Хеш добавлен!')
        setNewLink(''); fetchHashes()
        setTimeout(() => setAddStatus('idle'), 3000)
      } else {
        setAddStatus('error'); setAddMsg(data.message || 'Ошибка')
      }
    } catch (e: any) {
      setAddStatus('error'); setAddMsg('Ошибка: ' + e.message)
    }
  }

  const removeHash = async (id: number) => {
    try {
      await api(`/api/admin/vk/hashes/${id}`, { method: 'DELETE' })
      fetchHashes()
    } catch {}
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <h1 className="text-xl font-bold">VK TURN Хеши</h1>

      {/* Instructions */}
      <div className="bg-[#111] border border-[#4680C2]/30 rounded-xl p-5 space-y-3">
        <h2 className="font-semibold flex items-center gap-2 text-sm">
          <Link className="w-4 h-4 text-[#4680C2]" /> Как получить хеш
        </h2>
        <ol className="text-xs text-[#aaa] space-y-1.5 leading-relaxed list-decimal list-inside">
          <li>Открой <strong className="text-white">ВКонтакте</strong> → Группы → выбери любую свою группу</li>
          <li>Нажми <strong className="text-white">«Звонок»</strong> → <strong className="text-white">«Начать звонок»</strong></li>
          <li>Скопируй ссылку на звонок — она выглядит как <code className="text-[#4680C2]">vk.com/call/join/ХЕSH</code></li>
          <li>Вставь ссылку (или только хеш) в поле ниже</li>
          <li className="text-yellow-400">При завершении звонка нажимай <strong>«Просто завершить»</strong>, НЕ «Завершить для всех»</li>
        </ol>
      </div>

      {/* Add hash */}
      <div className="bg-[#111] border border-[#222] rounded-xl p-5 space-y-3">
        <h2 className="font-semibold text-sm">Добавить хеш</h2>
        <div className="flex gap-2">
          <input
            value={newLink}
            onChange={e => setNewLink(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && addHash()}
            placeholder="https://vk.com/call/join/AbCdEf123 или просто AbCdEf123"
            className="flex-1 bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2.5 text-sm text-white placeholder-[#555] focus:outline-none focus:border-[#4680C2] transition-colors"
          />
          <button onClick={addHash} disabled={!newLink || addStatus === 'loading'}
            className="flex items-center gap-1.5 px-4 py-2.5 bg-[#4680C2] hover:bg-[#3a6fad] text-white rounded-lg text-sm font-semibold transition-colors disabled:opacity-50">
            {addStatus === 'loading' ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
            Добавить
          </button>
        </div>
        <StatusBadge status={addStatus} msg={addMsg} />
      </div>

      {/* Hashes list */}
      <div className="bg-[#111] border border-[#222] rounded-xl p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-sm">Активные хеши ({hashes.length}/3)</h2>
          <button onClick={fetchHashes} className="text-[#555] hover:text-white transition-colors">
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>

        {hashes.length === 0 ? (
          <div className="text-center py-8 text-[#555]">
            <AlertTriangle className="w-8 h-8 mx-auto mb-2 text-yellow-500" />
            <p className="text-sm">Нет хешей. Создай звонок в VK и добавь ссылку выше.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {hashes.map((h, i) => (
              <div key={h.id ?? i} className="flex items-center gap-3 bg-[#151515] rounded-lg px-4 py-3">
                {h.is_active
                  ? <CheckCircle className="w-4 h-4 text-green-400 flex-shrink-0" />
                  : <XCircle className="w-4 h-4 text-red-400 flex-shrink-0" />}
                <span className="text-xs text-[#555] w-12 flex-shrink-0">Слот {i + 1}</span>
                <span className="font-mono text-xs flex-1 text-[#ccc] truncate">{h.hash}</span>
                <span className="text-xs text-[#555] flex-shrink-0">Сбоев: {h.fail_count ?? 0}</span>
                <button onClick={() => removeHash(h.id)}
                  className="text-[#555] hover:text-red-400 transition-colors flex-shrink-0">
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="bg-[#111] border border-yellow-900/50 rounded-xl p-4">
        <p className="text-xs text-yellow-500/80 leading-relaxed">
          Можно добавить до <strong>3 хешей</strong> — они используются параллельно для увеличения скорости.
          Хеш перестаёт работать если нажать «Завершить для всех» в звонке.
          Монитор автоматически помечает нерабочие хеши.
        </p>
      </div>
    </div>
  )
}
