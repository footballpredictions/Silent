import VkPage from './VkPage'

/**
 * Раньше: VK + olcrtc. Olcrtc снят с продукта (конфликт CPU с WDTT на Улье).
 * Страница оставлена под VK-хеши / обход вариант 1.
 */
export default function BypassPage({ token }: { token: string }) {
  return (
    <div className="space-y-10">
      <div>
        <h1 className="text-xl font-semibold text-white mb-1">VK / WDTT</h1>
        <p className="text-sm text-[#888]">
          Хеши звонков ВКонтакте и обход через WDTT. Вариант olcrtc (Телемост / WB) отключён.
        </p>
      </div>

      <section className="space-y-4">
        <VkPage token={token} />
      </section>
    </div>
  )
}
