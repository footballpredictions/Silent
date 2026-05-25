import { useState } from 'react'
import { setServerUrl } from '../api'

export default function ServerSetupScreen({ onDone }: { onDone: () => void }) {
  const [url, setUrl] = useState('https://')
  const [error, setError] = useState('')

  const handleSave = () => {
    if (!url.startsWith('http')) { setError('Введите корректный URL'); return }
    setServerUrl(url)
    onDone()
  }

  return (
    <div className="flex flex-col h-full bg-black text-white p-5">
      {/* Draggable title bar */}
      <div className="h-8 -mx-5 -mt-5 mb-4 flex items-center px-4 bg-black" style={{ WebkitAppRegion: 'drag' } as any}>
        <span className="text-xs text-gray-500 tracking-widest font-light">SILENT VPN</span>
      </div>

      <div className="flex-1 flex flex-col items-center justify-center gap-4">
        <div className="text-center mb-2">
          <div className="w-12 h-12 bg-white rounded-2xl flex items-center justify-center mx-auto mb-3">
            <span className="text-black font-bold text-lg">S</span>
          </div>
          <h1 className="font-bold text-base tracking-widest">SILENT</h1>
          <p className="text-gray-500 text-xs mt-1">Настройка сервера</p>
        </div>

        <div className="w-full">
          <label className="text-xs text-gray-500 mb-1 block uppercase tracking-wider">Адрес сервера</label>
          <input
            type="url"
            value={url}
            onChange={e => setUrl(e.target.value)}
            placeholder="https://1.2.3.4"
            className="w-full bg-gray-900 border border-gray-700 rounded-xl px-3 py-2.5 text-white text-sm focus:outline-none focus:border-white"
            style={{ userSelect: 'text' } as any}
          />
          {error && <p className="text-red-400 text-xs mt-1">{error}</p>}
        </div>

        <button onClick={handleSave}
          className="w-full bg-white text-black rounded-xl py-2.5 text-sm font-semibold hover:bg-gray-200 transition-colors">
          Продолжить
        </button>
      </div>
    </div>
  )
}
