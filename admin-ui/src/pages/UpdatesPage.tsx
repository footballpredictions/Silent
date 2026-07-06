import { useState, useEffect, useRef } from 'react'
import { Download, Trash2, Upload, Hammer, Square, Github, Copy } from 'lucide-react'

interface UpdateInfo {
  platform: string
  version: string | null
  filename: string | null
  uploaded_at: string | null
  size: number
  download_url?: string
  github_download_url?: string
  github_published_at?: string | null
}

interface GitHubStatus {
  configured: boolean
  repo: string
  landing_url: string
}

interface BuildStatus {
  running: boolean
  stop_requested?: boolean
  status: string
  message: string | null
  message_full?: string | null
  last_at: string | null
  last_platform: string | null
  bootstrap_hash: string | null
  nightly_date: string | null
  nightly_pc_enabled?: boolean
  nightly_android_enabled?: boolean
}

interface BuildConfig {
  nightly_pc_enabled: boolean
  nightly_android_enabled: boolean
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

function downloadHref(item: UpdateInfo): string | null {
  if (item.download_url) return item.download_url
  if (!item.filename) return null
  return `/update/${item.platform}/${encodeURIComponent(item.filename)}`
}

export default function UpdatesPage({ token }: { token: string }) {
  const [items, setItems] = useState<UpdateInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [msg, setMsg] = useState('')
  const [uploading, setUploading] = useState<string | null>(null)
  const [building, setBuilding] = useState<string | null>(null)
  const [buildStatus, setBuildStatus] = useState<BuildStatus | null>(null)
  const [buildConfig, setBuildConfig] = useState<BuildConfig | null>(null)
  const [savingConfig, setSavingConfig] = useState(false)
  const [stoppingBuild, setStoppingBuild] = useState(false)
  const [githubStatus, setGithubStatus] = useState<GitHubStatus | null>(null)
  const [publishingGithub, setPublishingGithub] = useState<string | null>(null)
  const [buildCopyToast, setBuildCopyToast] = useState(false)
  const pcRef = useRef<HTMLInputElement>(null)
  const androidRef = useRef<HTMLInputElement>(null)

  const headers = { Authorization: `Bearer ${token}` }

  const loadBuildStatus = async () => {
    try {
      const res = await fetch('/api/admin/updates/build-status', { headers })
      if (res.ok) setBuildStatus(await res.json())
    } catch { /* ignore */ }
  }

  const loadBuildConfig = async () => {
    try {
      const res = await fetch('/api/admin/updates/build-config', { headers })
      if (res.ok) setBuildConfig(await res.json())
    } catch { /* ignore */ }
  }

  const loadGithubStatus = async () => {
    try {
      const res = await fetch('/api/admin/updates/github-status', { headers })
      if (res.ok) setGithubStatus(await res.json())
    } catch { /* ignore */ }
  }

  const load = async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/admin/updates', { headers })
      if (res.ok) setItems(await res.json())
      await loadBuildStatus()
      await loadBuildConfig()
      await loadGithubStatus()
    } catch { /* ignore */ }
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  useEffect(() => {
    if (!buildStatus?.running && !building) return
    const t = setInterval(loadBuildStatus, 4000)
    return () => clearInterval(t)
  }, [buildStatus?.running, building, token])

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

  const buildRelease = async (platform: string) => {
    setBuilding(platform)
    setMsg('')
    try {
      const res = await fetch(`/api/admin/updates/build/${platform}`, {
        method: 'POST',
        headers,
      })
      const data: { detail?: string; message?: string } = await res.json().catch(() => ({}))
      if (!res.ok) {
        setMsg(typeof data.detail === 'string' ? data.detail : `Ошибка (${res.status})`)
        setBuilding(null)
      } else {
        setMsg(data.message || `Сборка ${platformLabel[platform]} запущена`)
        await loadBuildStatus()
      }
    } catch (e) {
      setMsg(e instanceof Error ? e.message : 'Ошибка сети')
      setBuilding(null)
    }
  }

  const publishGithub = async (platform: string) => {
    setPublishingGithub(platform)
    setMsg('')
    try {
      const res = await fetch(`/api/admin/updates/publish-github/${platform}`, {
        method: 'POST',
        headers,
      })
      const data: { detail?: string; message?: string; download_url?: string } = await res.json().catch(() => ({}))
      if (!res.ok) {
        setMsg(typeof data.detail === 'string' ? data.detail : `Ошибка (${res.status})`)
      } else {
        setMsg(data.message || `Опубликовано на GitHub (${platformLabel[platform]})`)
        await load()
      }
    } catch (e) {
      setMsg(e instanceof Error ? e.message : 'Ошибка сети')
    } finally {
      setPublishingGithub(null)
    }
  }

  const stopBuild = async () => {
    setStoppingBuild(true)
    setMsg('')
    try {
      const res = await fetch('/api/admin/updates/build-stop', {
        method: 'POST',
        headers,
      })
      const data: { detail?: string; message?: string } = await res.json().catch(() => ({}))
      if (!res.ok) {
        setMsg(typeof data.detail === 'string' ? data.detail : `Ошибка (${res.status})`)
      } else {
        setMsg(data.message || 'Остановка сборки запрошена')
        await loadBuildStatus()
      }
    } catch (e) {
      setMsg(e instanceof Error ? e.message : 'Ошибка сети')
    } finally {
      setStoppingBuild(false)
    }
  }

  const setNightlyFlag = async (platform: 'pc' | 'android', enabled: boolean) => {
    const prev = buildConfig
    const next: BuildConfig = {
      nightly_pc_enabled: platform === 'pc' ? enabled : !!prev?.nightly_pc_enabled,
      nightly_android_enabled: platform === 'android' ? enabled : !!prev?.nightly_android_enabled,
    }
    setBuildConfig(next)
    setSavingConfig(true)
    setMsg('')
    try {
      const body = platform === 'pc' ? { pc_enabled: enabled } : { android_enabled: enabled }
      const res = await fetch('/api/admin/updates/build-config', {
        method: 'POST',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await res.json().catch(() => null)
      if (!res.ok) {
        setBuildConfig(prev)
        setMsg(typeof data?.detail === 'string' ? data.detail : `Ошибка (${res.status})`)
      } else if (data) {
        setBuildConfig(data as BuildConfig)
      }
    } catch (e) {
      setBuildConfig(prev)
      setMsg(e instanceof Error ? e.message : 'Ошибка сети')
    } finally {
      setSavingConfig(false)
    }
  }

  useEffect(() => {
    if (buildStatus && !buildStatus.running && building) {
      setBuilding(null)
      if (buildStatus.status === 'ok') load()
    }
  }, [buildStatus?.running, buildStatus?.status])

  const copyBuildLog = async () => {
    const text = buildStatus?.message_full || buildStatus?.message
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.left = '-9999px'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    setBuildCopyToast(true)
    setTimeout(() => setBuildCopyToast(false), 2000)
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <h1 className="text-xl font-bold">Обновления клиентов</h1>
      <p className="text-[#555] text-sm">
        Файлы хранятся в папке <code className="text-[#888]">update/</code> на сервере.
        При загрузке новой версии старая удаляется автоматически.
        Клиенты проверяют обновления через VPN-туннель.
        AI-агент в <strong className="text-[#aaa]">00:00 МСК</strong> создаёт новый bootstrap-хеш
        и пересобирает релизы (версия не меняется).
        Скачивание на{' '}
        <a href="https://silentvpn3.github.io" target="_blank" rel="noreferrer" className="text-purple-300 underline">
          silentvpn3.github.io
        </a>{' '}
        — через GitHub Releases (работает без VPS).
      </p>

      {githubStatus && (
        <div className="bg-[#111] border border-[#222] rounded-xl p-4 text-sm text-[#888]">
          GitHub:{' '}
          <span className={githubStatus.configured ? 'text-green-400' : 'text-yellow-400'}>
            {githubStatus.configured ? `настроен (${githubStatus.repo})` : 'GITHUB_TOKEN не задан на сервере'}
          </span>
        </div>
      )}

      {buildStatus && (buildStatus.running || buildStatus.message) && (
        <div className="bg-[#111] border border-[#222] rounded-xl p-4 text-sm text-[#888] relative">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <p>
                Сборка:{' '}
                <span className={buildStatus.running ? 'text-yellow-400' : buildStatus.status === 'ok' ? 'text-green-400' : 'text-red-400'}>
                  {buildStatus.running ? 'в процессе' : buildStatus.status}
                </span>
                {buildStatus.last_platform && ` (${platformLabel[buildStatus.last_platform] || buildStatus.last_platform})`}
              </p>
              {buildStatus.message && (
                <p
                  className={`mt-1 break-words ${
                    buildStatus.status === 'error' ? 'line-clamp-3 text-red-300/90' : ''
                  }`}
                  title={buildStatus.status === 'error' ? 'Краткий превью — полный текст через «Копировать»' : undefined}
                >
                  {buildStatus.message}
                  {(buildStatus.message_full?.length ?? 0) > (buildStatus.message?.length ?? 0) && (
                    <span className="text-[#555]"> …</span>
                  )}
                </p>
              )}
              {buildStatus.bootstrap_hash && (
                <p className="mt-1 text-xs text-[#555]">Bootstrap: {buildStatus.bootstrap_hash.slice(0, 20)}…</p>
              )}
            </div>
            {buildStatus.message && !buildStatus.running && (
              <button
                type="button"
                onClick={copyBuildLog}
                className="shrink-0 inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium bg-[#1a1a1a] border border-[#333] text-[#ccc] hover:bg-[#222] hover:text-white transition-colors"
                title="Скопировать полный текст лога/ошибки сборки"
              >
                <Copy className="w-3.5 h-3.5" />
                Копировать
              </button>
            )}
          </div>
          {buildCopyToast && (
            <p className="absolute bottom-2 right-3 text-[11px] text-green-400">Скопировано</p>
          )}
        </div>
      )}

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
                      {item.github_download_url ? (
                        <p>
                          GitHub:{' '}
                          <a
                            href={item.github_download_url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-purple-300 underline break-all"
                          >
                            опубликовано
                          </a>
                          {item.github_published_at ? ` (${formatDate(item.github_published_at)})` : ''}
                        </p>
                      ) : (
                        <p className="text-[#666]">GitHub: не опубликовано</p>
                      )}
                    </div>
                  ) : (
                    <p className="text-sm text-[#555] mt-2">Нет загруженной версии</p>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setNightlyFlag(item.platform as 'pc' | 'android', !(
                      item.platform === 'pc' ? !!buildConfig?.nightly_pc_enabled : !!buildConfig?.nightly_android_enabled
                    ))}
                    disabled={savingConfig}
                    title="Включить/выключить ночную автосборку платформы"
                    className="inline-flex items-center gap-2 text-[#ccc] disabled:opacity-50"
                  >
                    <span className="text-xs font-medium">Авто 00:00</span>
                    <span
                      className={`relative inline-flex h-5 w-9 shrink-0 rounded-full transition-colors ${
                        (item.platform === 'pc' ? !!buildConfig?.nightly_pc_enabled : !!buildConfig?.nightly_android_enabled)
                          ? 'bg-purple-500'
                          : 'bg-[#333]'
                      }`}
                    >
                      <span
                        className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
                          (item.platform === 'pc' ? !!buildConfig?.nightly_pc_enabled : !!buildConfig?.nightly_android_enabled)
                            ? 'translate-x-4'
                            : 'translate-x-0.5'
                        }`}
                      />
                    </span>
                    <span className={`text-[11px] ${
                      (item.platform === 'pc' ? !!buildConfig?.nightly_pc_enabled : !!buildConfig?.nightly_android_enabled)
                        ? 'text-purple-300'
                        : 'text-[#666]'
                    }`}>
                      {(item.platform === 'pc' ? !!buildConfig?.nightly_pc_enabled : !!buildConfig?.nightly_android_enabled) ? 'ON' : 'OFF'}
                    </span>
                  </button>
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
              </div>

              <div className="mt-4 pt-4 border-t border-[#222] flex flex-wrap items-center gap-3">
                {downloadHref(item) && (
                  <a
                    href={downloadHref(item)!}
                    download={item.filename || true}
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
                <button
                  disabled={!item.version || !githubStatus?.configured || publishingGithub === item.platform}
                  onClick={() => publishGithub(item.platform)}
                  className="inline-flex items-center gap-2 bg-[#1a1a1a] border border-purple-900/50 text-purple-200 px-4 py-2 rounded-lg text-sm font-semibold hover:bg-[#221a2a] disabled:opacity-50"
                  title="Загрузить в GitHub Releases + обновить releases.json на silentvpn3.github.io"
                >
                  <Github className="w-4 h-4" />
                  {publishingGithub === item.platform ? 'Публикация…' : 'Опубликовать на GitHub'}
                </button>
                <button
                  disabled={building === item.platform || buildStatus?.running}
                  onClick={() => buildRelease(item.platform)}
                  className="inline-flex items-center gap-2 bg-[#1a1a1a] border border-[#333] text-white px-4 py-2 rounded-lg text-sm font-semibold hover:bg-[#222] disabled:opacity-50"
                  title="Новый bootstrap-хеш + сборка на сервере → update/"
                >
                  <Hammer className="w-4 h-4" />
                  {building === item.platform || (buildStatus?.running && buildStatus.last_platform === item.platform)
                    ? 'Сборка...'
                    : 'Собрать релиз в update'}
                </button>
                <button
                  disabled={
                    !buildStatus?.running ||
                    buildStatus.last_platform !== item.platform ||
                    stoppingBuild ||
                    !!buildStatus.stop_requested
                  }
                  onClick={stopBuild}
                  className="inline-flex items-center gap-2 bg-[#2a1111] border border-[#4a2222] text-red-300 px-4 py-2 rounded-lg text-sm font-semibold hover:bg-[#331414] disabled:opacity-50"
                  title="Остановить текущую сборку этой платформы"
                >
                  <Square className="w-4 h-4" />
                  {buildStatus?.running && buildStatus.last_platform === item.platform
                    ? (buildStatus.stop_requested ? 'Остановка запрошена…' : (stoppingBuild ? 'Останавливаем…' : 'Остановить сборку'))
                    : 'Остановить сборку'}
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
