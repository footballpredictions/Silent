interface VkLoginSectionProps {
  vkReady: boolean
  vkUserId: number | null
  bootstrapHash: string | null
  vkMsg: string
  linking: boolean
  onLinkVk: () => void
}

export default function VkLoginSection({
  vkReady,
  vkUserId,
  bootstrapHash,
  vkMsg,
  linking,
  onLinkVk,
}: VkLoginSectionProps) {
  return (
    <div className="mb-4">
      <p className="text-sm font-semibold text-black">Шаг 1 — VK</p>
      <p className="text-xs text-gray-500 mt-1.5">
        {vkReady && vkUserId
          ? `VK готов (ID ${vkUserId}). Можно войти в аккаунт.`
          : 'Привяжите VK — бот автоматически отправит первый хеш'}
      </p>
      {bootstrapHash && (
        <p className="text-[10px] text-[#4680C2] mt-1">Хеш: {bootstrapHash.slice(0, 16)}…</p>
      )}
      <button
        type="button"
        onClick={onLinkVk}
        disabled={vkReady || linking}
        className="w-full mt-3 py-2.5 rounded-xl text-xs font-medium text-white transition-colors disabled:opacity-40"
        style={{ background: '#4680C2' }}
      >
        {linking ? 'Ожидание VK…' : vkReady ? 'VK подключён' : 'Привязать VK ID'}
      </button>
      {vkMsg && <p className="text-xs text-gray-500 mt-2">{vkMsg}</p>}
      <hr className="my-4 border-gray-200" />
      <p className="text-sm font-semibold text-black">Шаг 2 — вход в Silent</p>
      <div className="mt-2" />
    </div>
  )
}
