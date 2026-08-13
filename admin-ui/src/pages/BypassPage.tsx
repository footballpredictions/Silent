import VkPage from './VkPage'
import Olcrtc2Panel from '../components/Olcrtc2Panel'

/**
 * Вариант 1: VK / WDTT на Улье.
 * Вариант 2: olcrtc 2.0 (Телемост) — exit на соте, без Playwright на queen.
 */
export default function BypassPage({ token }: { token: string }) {
  return (
    <div className="space-y-10">
      <div>
        <h1 className="text-xl font-semibold text-white mb-1">Варианты обхода</h1>
        <p className="text-sm text-[#888]">
          VK/WDTT на Улье и olcrtc 2.0 (Телемост) на отдельной соте — без конфликта CPU.
        </p>
      </div>

      <section className="space-y-4">
        <h2 className="text-base font-medium text-white">1. VK / WDTT</h2>
        <VkPage token={token} />
      </section>

      <section className="space-y-4">
        <h2 className="text-base font-medium text-white">2. olcrtc 2.0</h2>
        <Olcrtc2Panel token={token} />
      </section>
    </div>
  )
}
