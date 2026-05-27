import { useState } from 'react'

export default function HashInputSection({
  bootstrapHash,
  statusMsg,
  bootstrapConnecting,
  onConnect,
}: {
  bootstrapHash: string | null
  statusMsg: string
  bootstrapConnecting: boolean
  onConnect: (raw: string) => void
}) {
  const [input, setInput] = useState(bootstrapHash || '')

  return (
    <div className="mb-4">
      <p className="text-sm font-semibold text-black">Шаг 1 — хеш звонка VK</p>
      <p className="text-[11px] text-gray-500 mt-1 mb-2">
        Вставьте ссылку vk.com/call/join/… или хеш, затем подключитесь. Хеш сохранится автоматически.
      </p>
      <input
        className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-black"
        placeholder="Хеш или ссылка на звонок VK"
        value={input}
        onChange={e => setInput(e.target.value)}
        onKeyDown={e => {
          if (e.key === 'Enter' && input.trim() && !bootstrapConnecting) onConnect(input)
        }}
      />
      <button
        type="button"
        disabled={!input.trim() || bootstrapConnecting}
        onClick={() => onConnect(input)}
        className="w-full mt-2 py-2.5 rounded-xl text-sm font-medium bg-black text-white disabled:opacity-40"
      >
        {bootstrapConnecting ? 'Подключение…' : 'Подключить для входа'}
      </button>
      {statusMsg && <p className="text-[11px] text-gray-500 mt-2">{statusMsg}</p>}
      <div className="border-t border-gray-200 my-4" />
    </div>
  )
}
