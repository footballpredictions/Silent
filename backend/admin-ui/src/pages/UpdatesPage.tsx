import { useState, useEffect, useRef } from 'react'
import { Download, Trash2, Upload } from 'lucide-react'

interface UpdateInfo {
  platform: string
  version: string | null
  filename: string | null
  uploaded_at: string | null
  size: number
  download_url?: string
}

function formatSize(bytes: number): string {
  if (!bytes) return '—'
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('ru-RU')
  } catch {
    return iso
  }
}

const platformLabel: Record<string, string> = {
  pc: 'PC (Windows)',
  android: 'Android',
}

export default function UpdatesPage({ token }: { token: string }) {
  const [items, setItems] = useState<UpdateInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [msg, setMsg] = useState('')
  const [uploading, setUploading] = useState<string | null>(null)
  const pcRef = useRef<HTMLInputElement>(null)
  const androidRef = useRef<HTMLInputElement>(null)

  const headers = { Authorization: `Bearer ${token}` }

  const load = async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/admin/updates', { headers })
      if (res.ok) setItems(await res.json())
    } catch { /* ignore */ }
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  const upload = async (platform: string, file: File) => {
    setUploading(platform)
    setMsg('')
    const fd = new FormData()
    fd.append('platform', platform)
    fd.append('file', file)
    try {
      const res = await fetch('/api/admin/updates/upload', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      })
      let data: { detail?: string; version?: string; message?: string } = {}
      try { data = await res.json() } catch { /* non-json e.g. nginx 413 */ }
      if (!res.ok) {
        if (res.status === 413) setMsg('Файл слишком большой для сервера (лимит 200 МБ)')
        else setMsg(typeof data.detail === 'string' ? data.detail : `Ошибка загрузки (${res.status})`)
      } else {
        setMsg(`Загружено: ${platformLabel[platform]} v${data.version}`)
        await load()
      }
    } catch (e) {
      setMsg(e instanceof Error ? e.message : 'Ошибка сети')
    }
    setUploading(null)
  }

  const remove = async (platform: string) => {
    if (!confirm(`Удалить обновление для ${platformLabel[platform]}?`)) return
    setMsg('')
    try {
      await fetch(`/api/admin/updates/${platform}`, { method: 'DELETE', headers })
      setMsg('Удалено')
      await load()
    } catch {
      setMsg('Ошибка удаления')
    }
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <h1 className="text-xl font-bold">Обновления клиентов</h1>
      <p className="text-[#555] text-sm">
        Файлы хранятся в папке <code className="text-[#888]">update/</code> на сервере.
        При загрузке новой версии старая удаляется автоматически.
        Клиенты проверяют обновления через VPN-туннель.
      </p>

      {loading ? (
        <p className="text-[#666] text-sm">Загрузка...</p>
      ) : (
        <div className="space-y-4">
          {items.map(item => (
            <div key={item.platform} className="bg-[#111] border border-[#222] rounded-xl p-5">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 className="font-semibold">{platformLabel[item.platform] || item.platform}</h2>
                  {item.version ? (
                    <div className="mt-2 space-y-1 text-sm text-[#888]">
                      <p>Версия: <span className="text-white">{item.version}</span></p>
                      <p>Файл: {item.filename}</p>
                      <p>Размер: {formatSize(item.size)}</p>
                      <p>Загружено: {formatDate(item.uploaded_at)}</p>
                    </div>
                  ) : (
                    <p className="text-sm text-[#555] mt-2">Нет загруженной версии</p>
                  )}
                </div>
                {item.version && (
                  <button
                    onClick={() => remove(item.platform)}
                    className="p-2 text-[#666] hover:text-red-400 transition-colors"
                    title="Удалить"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                )}
              </div>

              <div className="mt-4 pt-4 border-t border-[#222] flex flex-wrap items-center gap-3">
                {item.download_url && (
                  <a
                    href={item.download_url}
                    download
                    className="inline-flex items-center gap-2 bg-[#1a1a1a] border border-[#2a2a2a] text-white px-4 py-2 rounded-lg text-sm font-semibold hover:bg-[#222] transition-colors"
                  >
                    <Download className="w-4 h-4" />
                    Скачать
                  </a>
                )}
                <input
                  ref={item.platform === 'pc' ? pcRef : androidRef}
                  type="file"
                  accept={item.platform === 'pc' ? '.exe,.msi' : '.apk'}
                  className="hidden"
                  onChange={e => {
                    const f = e.target.files?.[0]
                    if (f) upload(item.platform, f)
                    e.target.value = ''
                  }}
                />
                <button
                  disabled={uploading === item.platform}
                  onClick={() => (item.platform === 'pc' ? pcRef : androidRef).current?.click()}
                  className="inline-flex items-center gap-2 bg-white text-black px-4 py-2 rounded-lg text-sm font-semibold hover:bg-[#e0e0e0] disabled:opacity-50"
                >
                  <Upload className="w-4 h-4" />
                  {uploading === item.platform ? 'Загрузка...' : 'Загрузить файл'}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {msg && <p className="text-sm text-[#888]">{msg}</p>}
    </div>
  )
}
