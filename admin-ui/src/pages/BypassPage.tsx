import VkPage from './VkPage'

/**
 * VK-only bypass page.
 */
export default function BypassPage({ token }: { token: string }) {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-white mb-1">Варианты обхода</h1>
        <p className="text-sm text-[#888]">
          Только VK / WDTT. Выбор сервера выполняется на клиенте через API `/api/vpn/servers`.
        </p>
      </div>

      <section className="space-y-4">
        <h2 className="text-base font-medium text-white">VK / WDTT</h2>
        <VkPage token={token} />
      </section>
    </div>
  )
}
